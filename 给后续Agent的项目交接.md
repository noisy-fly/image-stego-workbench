# 图片隐写工作台：给下一位 Agent 的交接

## 项目和用户目标

这是面向 CTF 初学者的中文 Windows 图片隐写桌面工具，优先简洁、图形化、本地处理。工作区就是本文件所在目录；用户喜欢通过导入图片、画布拖拽及单图分析完成操作，避免复杂菜单和大模型依赖。保留原图，不复制未获许可的 StegSolve-NG 源码；底层是独立实现。

GitHub 仓库：https://github.com/noisy-fly/image-stego-workbench （公开）。用户希望按阶段 commit、推送，功能完成后构建 Windows 可安装版并配置 Release；推送 vX.Y.Z 标签会触发 `.github/workflows/` 中的构建。安装版启动自动检查 Release，设置中可手动检查。操作前查看 `git status` 与最新 Release，勿覆盖用户改动。不要将用户凭据或样题答案写进提交/文档。

## 运行、验证与发布

Windows 下 `py -3 -m pip install -r requirements.txt`，然后 `py -3 app.py`；也可运行 `启动.bat`。主要依赖 PySide6、Pillow、NumPy、PyAV。无显示测试设置 `QT_QPA_PLATFORM=offscreen`，逐文件运行 `py -3 -m unittest discover -s tests -p test_文件名.py -q`；启动自检 `py -3 app.py --smoke-test`。CI 按标签编译 PyInstaller 和 Inno Setup，验证测试、安装、启动和卸载，并发布 `StegoWorkbench-Setup.exe` 与 `SHA256.txt`。源码版本在 `app_version.py`，打包时覆盖版本；发版前检查测试中的模拟版本。

## 主要结构

- `app.py`：主窗口、画布图卡及连线、导入、单图分析 `Analysis`、快捷键、LSB 快速检查和手动提取；图卡 source_ref 指向原文件并经复制/撤销保留，生成图无来源。
- `core.py`：图像、双图、多图运算；`extract_bits` 的通道和位按传入顺序读取；`scan_lsb` 常规检查；`scan_lsb_conditional` 是条件排列检查。
- `conditional_lsb.py`：条件 LSB 检查对话框和工作线程。用户选定通道、位、行列和起点，可遍历所选通道及位的排列，并可尝试后续 0–7 位对齐；最多 4096 组合，单组合检查前 65536 个像素。开始后暂不能取消；结果依据有限文件头和花括号文本，仅为候选。
- `file_inspection.py`、`file_dialog.py`：对原始文件字节全范围流式查找有限已知签名，展示候选并保存从偏移到 EOF；不自动解压执行。文件头候选最多 512 条；PNG/JPEG/GIF 尾部结构可判定；ZIP 不大于 128 MiB 时可通过中央目录查找可能受损的本地文件头。无法保证识别未知/加密/任意破坏文件头，候选可能误报；ZIP 损坏头仅定位，不自动修复。图片像素编码中的隐写不属于这种字节签名扫描。
- `png_repair.py`：正常解码失败时，有限范围根据 IHDR CRC 恢复单一宽或高，需唯一候选且解码成功，不改原文件。
- `bmp_repair.py`：对未压缩 BMP 数据长度与高度不一致时，计算候选行数；用户确认后内存中修补高度并解码。多余数据可能是附加文件，候选不能当成原始尺寸的证明。`misc24.bmp` 标高 150，候选 250，剩余 2 字节。
- `extract_sources.py`、`extract_dialog.py`：从视频/GIF/ZIP/TAR/部分字幕提取并分组；`workflow_canvas.py` 为另一个图形工作流。
- `updater.py` / 相关更新 UI：GitHub Release 检查、跳过版本、下载校验及安装；`tests/` 包含像素、画布、文件、更新和媒体等测试。
- `README.md` 面向用户；`task.md` 为阶段进度；`.github/RELEASE_NOTES.md` 是发布说明模板。

## 后续维护注意

所有原文件检查以导入时的路径、大小和修改时间核对来源，变化后要求重新导入；保存提取数据不可覆盖原图。不要假称能发现所有隐写文件或识别任意修改的文件头。无损复制字节与像素重新编码不同；目前保存候选是从偏移到文件末尾，可能包括其他字节。ZIP 中央目录匹配不代表密文可解压或文件完整。BMP 自动推断必须保留用户选择，不可静默修改原图。Windows 打包对 Qt、PyAV 特别敏感，优先观察 CI 全量测试和安装自检。
