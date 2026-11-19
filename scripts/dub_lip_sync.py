"""Render one prepared speaking shot with installed MuseTalk 1.5 assets."""

import argparse
from contextlib import contextmanager
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile


FPS = 25
AUDIO_SAMPLE_RATE = 16000
MAX_FRAMES = 30 * FPS
ASSETS = {
    'musetalk/musetalk.json': '5b6923aee04d71692e0e9846c471e0a4ea07a4f686d39545e472bd4ba17e1b47',
    'musetalk/unet.pth': '7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007',
    'whisper/config.json': 'ffdccec4f3211f4c63310f2b7098f309fe70f3952cedc5e4d11e43f5b2379b98',
    'whisper/model.safetensors': '7ebd0e69e78190ffe1438491fa05cc1f5c1aa3a4c4db3bc1723adbb551ea2395',
    'whisper/preprocessor_config.json': '9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666',
    'vae/config.json': '92d3dfb746fca211a2c9e019e285f8597412211728dce3c5bcf4eda0f2d62e7e',
    'vae/diffusion_pytorch_model.safetensors': 'a1d993488569e928462932c8c38a0760b874d166399b14414135bd9c42df5815',
    'yunet.onnx': '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
}
INPUT = ('-protocol_whitelist', 'file,pipe', '-i')


def sha256(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, timeout=120).stdout


def probe(path):
    return json.loads(run('ffprobe', '-v', 'error', '-show_streams', '-of', 'json', *INPUT, str(path)))['streams']


def video_contract(streams):
    videos = [stream for stream in streams if stream['codec_type'] == 'video']
    if len(videos) != 1:
        raise ValueError('Expected one video stream')
    video = videos[0]
    width, height = video['width'], video['height']
    frames = int(video['nb_frames'])
    if (not 2 <= width <= 1920 or not 2 <= height <= 1080 or width % 2 or height % 2
            or video['r_frame_rate'] != '25/1' or not 1 <= frames <= MAX_FRAMES
            or abs(float(video['start_time'])) > .001
            or abs(float(video['duration']) - frames / FPS) > .002):
        raise ValueError('Prepare a zero-based 25 fps shot of up to 30 seconds at up to 1920×1080')
    return width, height, frames


def audio_contract(streams, frames):
    if len(streams) != 1 or streams[0]['codec_type'] != 'audio':
        raise ValueError('Provide an audio-only track')
    audio = streams[0]
    start = float(audio.get('start_time', 0))
    duration = float(audio['duration'])
    if not math.isfinite(start) or not math.isfinite(duration) or abs(start) > .001 or abs(duration - frames / FPS) > .002:
        raise ValueError('Audio and video must cover the same zero-based timeline')


def frame_timing(entries, frames):
    times = [float(frame['best_effort_timestamp_time']) for frame in entries]
    if len(times) != frames or any(not math.isfinite(time) or abs(time-i/FPS) > .002 for i, time in enumerate(times)):
        raise ValueError('The shot does not have a constant 25 fps presentation timeline')


@contextmanager
def media_pipe(command, **kwargs):
    with subprocess.Popen(command, **kwargs) as process:
        try:
            yield process
            if process.wait(timeout=20):
                raise ValueError('FFmpeg did not complete')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def frames_from(pipe, width, height, frame_count, numpy):
    length = width * height * 3
    for _ in range(frame_count):
        frame = pipe.read(length)
        if len(frame) != length:
            raise ValueError('The decoded shot ended before its declared last frame')
        yield numpy.frombuffer(frame, numpy.uint8).reshape(height, width, 3)
    if pipe.read(1):
        raise ValueError('The shot contains more frames than declared')


def composite(frame, patch, geometry, fade, cv2, np):
    x0, y0, x1, y1, mouth_x, mouth_y, width, height = geometry
    image = frame[y0:y1, x0:x1]
    patch = cv2.resize(patch, (x1-x0, y1-y0), interpolation=cv2.INTER_LANCZOS4)
    yy, xx = np.ogrid[y0:y1, x0:x1]
    ellipse = ((xx-mouth_x)/(width*.36))**2 + ((yy-mouth_y-height*.04)/(height*.21))**2
    alpha = np.clip((1-ellipse)/.43, 0, 1) * fade
    alpha *= np.clip((yy-(mouth_y-height*.18))/(height*.055), 0, 1)
    border = (ellipse > .83) & (ellipse < 1.12)
    if np.count_nonzero(border) > 40:
        delta = np.median(image[border].astype(np.float32)-patch[border], axis=0)
        patch = np.clip(patch.astype(np.float32)+np.clip(delta, -8, 8)*.6, 0, 255)
    alpha = cv2.GaussianBlur(alpha.astype(np.float32), (0, 0), 2)[..., None]
    result = np.round(image*(1-alpha) + patch*alpha).astype(np.uint8)
    changed = int(np.count_nonzero(np.any(result != image, axis=-1)))
    image[:] = result
    return changed


def render(video, dialogue, mix, models, output):
    import cv2
    import numpy as np
    from diffusers import AutoencoderKL, UNet2DConditionModel
    from scipy.ndimage import gaussian_filter1d, median_filter
    import torch
    from transformers import WhisperFeatureExtractor, WhisperModel

    if not torch.cuda.is_available():
        raise ValueError('The installed renderer requires CUDA')
    width, height, frame_count = video_contract(probe(video))
    audio_contract(probe(dialogue), frame_count)
    audio_contract(probe(mix), frame_count)
    original_frames = run('ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                          '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', *INPUT, str(video))
    frame_timing(json.loads(original_frames)['frames'], frame_count)
    for name, expected in ASSETS.items():
        if sha256(models/name) != expected:
            raise ValueError(f'Incorrect installed model asset: {name}')

    decoder = ['ffmpeg', '-v', 'error', '-nostdin', '-xerror', *INPUT, str(video),
               '-map', '0:v:0', '-an', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-']
    cv2.setNumThreads(2)
    detector = cv2.FaceDetectorYN.create(str(models/'yunet.onnx'), '', (640, 360), score_threshold=.78)
    tracks = []
    with media_pipe(decoder, stdout=subprocess.PIPE) as reader:
        for frame in frames_from(reader.stdout, width, height, frame_count, np):
            _, faces = detector.detect(cv2.resize(frame, (640, 360)))
            if faces is None or len(faces) != 1:
                raise ValueError(f'Need one trackable face throughout the shot (frame {len(tracks)})')
            scale = np.tile([width/640, height/360], 7)
            tracks.append(faces[0, :14] * scale)
    stable = gaussian_filter1d(median_filter(tracks, size=(3, 1)), sigma=1.2, axis=0)
    geometry = []
    for track in stable:
        x, y, w, h = track[:4]
        nose_y = track[9]
        mouth_x, mouth_y = (track[10:12]+track[12:14])/2
        bottom = y+h*1.06
        bbox = (max(0, round(x+w*.015)), max(0, round(nose_y-(bottom-nose_y)*.87)),
                min(width, round(x+w*.985)), min(height, round(bottom)))
        if bbox[2]-bbox[0] < 32 or bbox[3]-bbox[1] < 32:
            raise ValueError('The face crop is too small')
        geometry.append((*bbox, mouth_x, mouth_y, w, h))

    sound = run('ffmpeg', '-v', 'error', '-nostdin', *INPUT, str(dialogue), '-vn', '-ac', '1',
                '-ar', str(AUDIO_SAMPLE_RATE), '-f', 'f32le', '-')
    pcm = np.frombuffer(sound, '<f4').copy()
    samples = frame_count * AUDIO_SAMPLE_RATE // FPS
    if abs(len(pcm) - samples) > 32 or not np.isfinite(pcm).all() or np.max(np.abs(pcm), initial=0) < .001:
        raise ValueError('Aligned dialogue is silent, invalid, or the wrong duration')
    pcm = np.pad(pcm[:samples], (0, max(0, samples-len(pcm))))

    torch.set_num_threads(4)
    device = torch.device('cuda:0')
    with torch.inference_mode():
        loader = WhisperFeatureExtractor.from_pretrained(models/'whisper', local_files_only=True)
        whisper = WhisperModel.from_pretrained(models/'whisper', local_files_only=True, use_safetensors=True).eval()
        features = loader(pcm, sampling_rate=AUDIO_SAMPLE_RATE, return_tensors='pt').input_features
        hidden = torch.stack(whisper.encoder(features, output_hidden_states=True).hidden_states, dim=2)
        hidden = torch.nn.functional.pad(hidden[0, :frame_count*2], (0, 0, 0, 0, 4, 12))
        context = torch.stack([hidden[2*i:2*i+10].reshape(50, 384) for i in range(frame_count)])
        frequency = 10000 ** (-torch.arange(0, 384, 2, dtype=torch.float32)/384)
        phase = torch.arange(50, dtype=torch.float32)[:, None] * frequency
        context[:, :, 0::2] += phase.sin()
        context[:, :, 1::2] += phase.cos()
        del whisper

        with torch.device('meta'):
            unet = UNet2DConditionModel(**json.loads((models/'musetalk/musetalk.json').read_text(encoding='utf-8')))
        weights = torch.load(models/'musetalk/unet.pth', map_location='cpu', weights_only=True, mmap=True)
        unet.load_state_dict(weights, strict=True, assign=True)
        del weights
        unet.to(device=device, dtype=torch.float16).eval()
        vae = AutoencoderKL.from_pretrained(models/'vae', local_files_only=True, use_safetensors=True).to(device).eval()
        timestep = torch.zeros(1, device=device, dtype=torch.long)

        with tempfile.TemporaryDirectory(prefix='.lip-sync-', dir=output.parent) as temporary:
            staged = Path(temporary)/'shot.mp4'
            encoder = ['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-video_size',
                       f'{width}x{height}', '-framerate', str(FPS), *INPUT, 'pipe:0', *INPUT, str(mix),
                       '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-crf', '15', '-pix_fmt', 'yuv420p',
                       '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', str(staged)]
            edits = []
            with media_pipe(decoder, stdout=subprocess.PIPE) as reader, media_pipe(encoder, stdin=subprocess.PIPE) as writer:
                source = frames_from(reader.stdout, width, height, frame_count, np)
                for start in range(0, frame_count, 2):
                    batch = list(itertools.islice(source, 2))
                    crops = []
                    for i, frame in enumerate(batch, start):
                        x0, y0, x1, y1 = geometry[i][:4]
                        crop = cv2.resize(frame[y0:y1, x0:x1], (256, 256), interpolation=cv2.INTER_LANCZOS4)
                        crops.append(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                    images = torch.from_numpy(np.array(crops)).permute(0, 3, 1, 2).to(device).float()/255
                    masked = images.clone()
                    masked[:, :, 128:] = 0
                    latent = torch.cat([vae.encode(masked*2-1).latent_dist.mode(),
                                        vae.encode(images*2-1).latent_dist.mode()], dim=1) * vae.config.scaling_factor
                    prompt = context[start:start+len(batch)].to(device=device, dtype=torch.float16)
                    prediction = unet(latent.half(), timestep, encoder_hidden_states=prompt).sample
                    result = vae.decode(prediction.float()/vae.config.scaling_factor).sample
                    if not torch.isfinite(result).all():
                        raise ValueError('Invalid generated frame')
                    patches = ((result/2+.5).clamp(0, 1).permute(0, 2, 3, 1)*255).round().byte().cpu().numpy()[..., ::-1]
                    for i, (frame, patch) in enumerate(zip(batch, patches), start):
                        frame = frame.copy()
                        edits.append(composite(frame, patch, geometry[i], min(1, (i+1)/4, (frame_count-i)/4), cv2, np))
                        writer.stdin.write(frame.tobytes())
                next(source, None)  # finish the decoder's frame-count check
                writer.stdin.close()

            output_streams = probe(staged)
            if not any(edits) or video_contract(output_streams) != (width, height, frame_count):
                raise ValueError('No generated mouth edits or mismatched output timeline')
            audio_contract([stream for stream in output_streams if stream['codec_type'] == 'audio'], frame_count)
            run('ffmpeg', '-v', 'error', '-nostdin', '-xerror', *INPUT, str(staged), '-map', '0:v:0',
                '-map', '0:a:0', '-f', 'null', '-')
            digest = sha256(staged)
            if os.name == 'nt':
                # On Windows rename refuses an existing destination. Some
                # sandboxes and filesystems disallow hard links.
                staged.rename(output)
            else:
                os.link(staged, output)
    return {'renderer': 'musetalk-1.5', 'artifact_sha256': digest, 'frame_count': frame_count,
            'duration_ms': frame_count * 1000 // FPS, 'changed_frames': sum(count > 0 for count in edits),
            'mouth_and_sync_review': 'unverified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('video', 'dialogue', 'mix', 'models', 'output'):
        parser.add_argument(f'--{argument}', required=True, type=Path)
    args = parser.parse_args()
    video, dialogue, mix, models, output = (getattr(args, key).resolve() for key in ('video', 'dialogue', 'mix', 'models', 'output'))
    if (video.suffix.lower() != '.mp4' or dialogue.suffix.lower() != '.wav' or mix.suffix.lower() != '.wav'
            or output.suffix.lower() != '.mp4' or output.exists() or not output.parent.is_dir()
            or not all(path.is_file() for path in (video, dialogue, mix))):
        parser.error('Provide an existing MP4, two WAV files, and a new MP4 path in an existing directory')
    try:
        print(json.dumps(render(video, dialogue, mix, models, output)))
    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f'Lip-sync failed: {exc}\n')


if __name__ == '__main__':
    main()
