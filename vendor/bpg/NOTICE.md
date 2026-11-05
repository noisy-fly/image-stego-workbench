# BPG 解码组件来源

`bpgdec.exe`、`libpng16-16.dll` 和 `zlib1.dll` 来自 Fabrice Bellard 发布的 libbpg 0.9.8 Windows 64 位压缩包：
https://bellard.org/bpg/bpg-0.9.8-win64.zip

压缩包 SHA-256：44034757c7dbf44498bfdb4c28b8ed3fbc498b32e7d18de4b98a6995371d457c。
上游源码： https://bellard.org/bpg/libbpg-0.9.8.tar.gz 。上游 README 说明 bpgdec / libbpg 使用 LGPL，BPG 特定部分使用 BSD 许可。二进制标识显示 libpng 1.6.10 和 zlib 1.2.8；其上游许可文本随此目录提供。发行前仍需核对 Windows 二进制中各组件的具体版本、许可文本及源码提供要求。

sample.bpg 是本项目自行生成的纯色测试图。
