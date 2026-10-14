# nixcraft

用 Nix flake 打包 [storytold](https://github.com/storytold) 的 Craft 系列桌面应用（纯 Rust）。

[English](README.en.md)

## 包含的软件包

| 包名 | 说明 |
| --- | --- |
| `photocraft` | 图层图像编辑 |
| `pdfcraft` | PDF 编辑 |
| `filmcraft` | 视频编辑 |
| `lightcraft` | 相册与非破坏性 RAW 冲印 |
| `wordcraft` | 文字处理 |
| `vectorcraft` | 矢量图形 |
| `effectcraft` | 动态图形 / 特效 |
| `gridcraft` | 电子表格 |
| `cadcraft` | CAD 建模 |
| `designcraft` | 平面设计 |
| `deckcraft` | 演示文稿 |
| `soundcraft` | 音频编辑 |
| `figcraft` | 界面设计 |

每个包通常提供 GUI 程序 `<名字>` 和命令行 / MCP 程序 `<名字>-cli`。`default` / `all` 是全部包的合集。

未打包：`artcraft`（Tauri + npm 前端）、`artcraftx`、`craft-launcher`。Web（wasm）版本亦不包含。

支持平台：`x86_64-linux`、`aarch64-linux`（CI 目前只构建前者）。

## 快速使用

```sh
nix run github:Biaogo/nixcraft#photocraft
nix build github:Biaogo/nixcraft#gridcraft
nix build github:Biaogo/nixcraft   # 全部
```

## 加入 flake / NixOS

```nix
# flake.nix
inputs.nixcraft = {
  url = "github:Biaogo/nixcraft";
  # Optional: follow your own nixpkgs (needs rustc ≥ 1.95; unstable recommended)
  # inputs.nixpkgs.follows = "nixpkgs";
};

# In a NixOS module (or home-manager / nix-darwin equivalent):
{
  nixpkgs.overlays = [ inputs.nixcraft.overlays.default ];
  environment.systemPackages = with pkgs; [
    photocraft
    lightcraft
    # or: nixcraft-all
  ];
}
```

也可以直接使用 `inputs.nixcraft.packages.${system}.photocraft`，不必挂 overlay。

## Cachix 二进制缓存

CI 会把成功构建的**最终输出**推到公开缓存 [biaogo](https://app.cachix.org/cache/biaogo)（不推构建时依赖）。在 Nix / NixOS 配置中加入：

```nix
nix.settings = {
  substituters = [ "https://biaogo.cachix.org" ];
  trusted-public-keys = [
    "biaogo.cachix.org-1:pEsKASFTETzWAVGGsjpHnq869V5KNeDOBhQahLlrPzY="
  ];
};
```

公钥来自 [Cachix API](https://cachix.org/api/v1/cache/biaogo)。若 fork 本仓库并推送缓存，请在 GitHub Actions 中配置 `CACHIX_AUTH_TOKEN`；**已在运行的 workflow 看不到中途新加的 Secret，需重新触发一次**。

## CI

`.github/workflows/build.yml`：

- **触发**：每天 **00:00（Asia/Shanghai）**、`workflow_dispatch`、push 到 `main`（忽略只改 `flake.lock` 的提交）
- **`force`**：即使已是最新 GitHub Release，也会构建并 `cachix push` / `pin`；**不会**改各包源的 lock 条目
- **`bump_nixpkgs`**：定时任务**总会**执行 `nix flake update nixpkgs`；手动运行仅在勾选时执行。bump 会像 force 一样重建并推送全部包，并把新的 nixpkgs 锁经 `commit-lock` 写回（提交信息含 `[skip ci]`）。与 `force` 相互独立，可同时勾选
- **包源**：查询 `storytold/<包>` 最新 Release；与锁相同且未 force/bump 则跳过；有新版本则锁到该 tag，再构建、push、pin
- **Cachix**：构建实际发生时若缺少 `CACHIX_AUTH_TOKEN`，推送步骤会失败。请取消后重新 `workflow_dispatch`（可开 force / bump_nixpkgs）
- **回写**：`commit-lock` 合并有变更的包源节点以及（若有）nixpkgs 节点，由 github-actions[bot] 推送

## 说明与限制

- 默认 `doCheck = false`（上游测试较慢，部分需要 GPU 或语料）
- 跟随 nixos-unstable（需要较新的 rustc）；嵌入 `craft-fonts` 以支持 CJK 字形
- 程序通过 wrapper 设置 `LD_LIBRARY_PATH`（Wayland / X11 / Vulkan / dbus / alsa）；NixOS 请开启 `hardware.graphics.enable`
- `pdfcraft` 对 `rten-gemm` 0.26 有一处针对 rustc 1.98 / LLVM 21 的临时补丁；上游升级该依赖后可能需调整

```sh
nix fmt    # nixfmt-tree
nix flake update photocraft-src
```
