# MediaLink 官网

官网是独立的 Vite 静态项目。页面内容直接写入 HTML，图库和滚动动效由原生 JavaScript 增强。站点不调用平台 API，无需服务器或运行时密钥。

## 本地运行

在仓库根目录执行，使用 Node.js 24。

```powershell
cd website
npm ci
npm run dev
```

打开 Vite 输出的地址。验证生产构建时，在同一目录执行以下命令，并打开预览地址中的 `/medialink-downloader/`。

```powershell
npm run build
npm run preview
```

## 发布

1. 在仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
2. 将官网改动提交到 `main`。官网文件或工作流变更会触发 **MediaLink website**。如果工作流已提交后才开启 Pages，可在 **Actions → MediaLink website → Run workflow** 选择 `main` 手动运行。
3. 在工作流确认构建与部署均成功后，访问 [官网](https://stelliakkk.github.io/medialink-downloader/)。

工作流仅上传 `website/dist`。Vite 的 `base` 已设置为 `/medialink-downloader/`。如果将站点迁移到不同的路径，需要同步更新 Vite 配置、canonical 和 Open Graph URL。

## 界面素材

`assets/` 中的三张 WebP 由 v3.0.6 桌面程序实际渲染，使用隔离的本地演示数据库和原创封面。站点图标来自桌面程序现有的 `app_icon()`。官网以 README、CHANGELOG、发布说明和界面代码为事实依据。升级展示版本时，请同步核对页面中的版本文字、功能描述和截图。

从仓库根目录重拍，使用已安装本项目依赖的 Python 环境。

```powershell
.\.venv\Scripts\python.exe website\tools\capture.py
```
