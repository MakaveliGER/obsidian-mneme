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
