// Stub for the `obsidian` runtime module so vitest can import files that
// reference it. None of these classes have behavior — if a test needs real
// plugin behavior, it belongs in Obsidian itself, not here.

export class Plugin {}
export class PluginSettingTab {}
export class Setting {
  setName(_: string): this { return this; }
  setDesc(_: string): this { return this; }
  addText(_cb: unknown): this { return this; }
  addToggle(_cb: unknown): this { return this; }
  addDropdown(_cb: unknown): this { return this; }
  addSlider(_cb: unknown): this { return this; }
  addButton(_cb: unknown): this { return this; }
}
export class Notice {
  constructor(_msg: string, _timeout?: number) {}
  hide(): void {}
}
export class Modal {}
export class ItemView {}
export class WorkspaceLeaf {}
export class App {}
export function addIcon(_name: string, _svg: string): void {}

/** Stub for Obsidian's requestUrl. Tests can override via vi.mock() if they
 * need controlled responses; by default, returns an empty 200. */
export async function requestUrl(_opts: {
  url: string;
  method?: string;
  headers?: Record<string, string>;
  body?: string | ArrayBuffer;
  throw?: boolean;
}): Promise<{ status: number; text: string; json: unknown; arrayBuffer: ArrayBuffer; headers: Record<string, string> }> {
  return {
    status: 200,
    text: "",
    json: null,
    arrayBuffer: new ArrayBuffer(0),
    headers: {},
  };
}
