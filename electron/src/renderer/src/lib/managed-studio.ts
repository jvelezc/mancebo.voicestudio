/** Display configuration supplied by the authenticated Mancebo gateway.
 * These flags never authorize backend operations. Standalone builds keep their
 * local identity and make no Mancebo calls unless the gateway opts them in. */
export type ManagedStudio = {
  workspaceId: string;
  canOperate: boolean;
  platformAdmin: boolean;
};

export type ManagedStudioWindow = {
  __MANCEBO_STUDIO__?: unknown;
  __OMNIVOICE_API_BASE__?: string;
  location: { origin: string };
};

export type StudioMode =
  | { kind: 'standalone' }
  | { kind: 'invalid' }
  | { kind: 'managed'; studio: ManagedStudio };

const canonicalWorkspace = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function readStudioMode(web: boolean, win?: ManagedStudioWindow): StudioMode {
  if (!web || !win || !Object.hasOwn(win, '__MANCEBO_STUDIO__')) return { kind: 'standalone' };
  const value = win.__MANCEBO_STUDIO__;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return { kind: 'invalid' };
  const data = value as Record<string, unknown>;
  if (
    typeof data.workspaceId !== 'string' ||
    !canonicalWorkspace.test(data.workspaceId) ||
    data.workspaceId === '00000000-0000-0000-0000-000000000000' ||
    typeof data.canOperate !== 'boolean' ||
    typeof data.platformAdmin !== 'boolean' ||
    win.location.origin !== 'https://api.mancebo.ai' ||
    win.__OMNIVOICE_API_BASE__?.replace(/\/+$/, '') !==
      `https://api.mancebo.ai/studio/workspaces/${data.workspaceId}`
  )
    return { kind: 'invalid' };
  return {
    kind: 'managed',
    studio: {
      workspaceId: data.workspaceId,
      canOperate: data.canOperate,
      platformAdmin: data.platformAdmin,
    },
  };
}

export function studioMode(): StudioMode {
  return readStudioMode(__WEB_DEPLOYMENT__, typeof window === 'undefined' ? undefined : window);
}

export function studioWorkspaceUrl(studio?: ManagedStudio): string {
  const url = new URL('https://mancebo.ai/voice-studio');
  if (studio) url.searchParams.set('business', studio.workspaceId);
  return url.toString();
}

export function requestStudioReconnect(studio: ManagedStudio): void {
  if (window.parent !== window) {
    // No credential or token crosses postMessage; the parent repeats its own
    // existing authenticated Edge launch and verifies this frame's source.
    window.parent.postMessage(
      { type: 'mancebo.studio.reconnect', workspace_id: studio.workspaceId },
      'https://mancebo.ai',
    );
  }
}
