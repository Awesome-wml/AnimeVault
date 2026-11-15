# 桌面版随包 ffmpeg：调用点、解析器与许可证调研

> 许可证部分是调研者（AI）基于官方页面做的**理解，不是法律意见，需要法务确认**。标注 [未验证] 的是没有亲自核实的点。
> 调研日期 2026-11-15，各来源的页面内容以当时为准。

## 1. 调用点清点（backend/ 下全部）

| 位置 | 用途 | 工具 | 命令行要点 | 需要的编码器/滤镜 |
|---|---|---|---|---|
| `core/tts_mix.py` `probe_seconds` | 读单句配音时长 | ffprobe | `-show_entries format=duration -of json` | 无（只解复用） |
| `core/tts_mix.py` `mix_lines` | 多句配音按起点拼成一条 mp3 | ffmpeg | `-filter_complex` 用 `aresample/aformat/adelay/amix/apad/atrim`；`-ac 1 -b:a 128k`，输出 `.mp3` | 解码 mp3；**编码 mp3 需要 libmp3lame**（ffmpeg 没有原生 mp3 编码器）；滤镜都是原生 |
| `api/video.py`（`use_prev_frame`） | 取上一段视频尾帧作参考图 | ffmpeg | `-sseof -0.5 -i x.mp4 -frames:v 1 x.png` | 解码 H.264/H.265（原生）；输出 PNG（原生） |
| `core/doubao_automation.py` 下载视频后 | 截尾帧存参考图 | ffmpeg | 同上 | 同上 |

结论：
- 后端**没有**视频拼接、转码、字幕烧录；导出剪映走 JSON 草稿，不调 ffmpeg。全部只用 ffmpeg 解码 + PNG/MP3 输出，**没有任何 H.264/H.265 编码需求**，也没有 libx264 依赖。
- 唯一的非原生依赖是 **libmp3lame**（LGPL 库，LGPL 构建可带）。
- 没有用到滤镜库以外的第三方库（libass、freetype 等都不需要）。
- 测试里 `tests/test_segments.py` 也用 ffmpeg/ffprobe（测试用，随包不需要）。
- 所有调用点已改为经 `core/ffmpeg_locator.py` 取路径，命令参数不变。

## 2. 解析器（`backend/core/ffmpeg_locator.py`）

顺序：`DONGAI_FFMPEG_BIN` / `DONGAI_FFPROBE_BIN`（指向不存在的文件直接报错，不再往下找）→ 包内 `bin/ffmpeg[.exe]`
（依次看 `DONGAI_APP_DIR`——`desktop_entry` 启动时设为可执行包目录；`DONGAI_RESOURCES_DIR`；`sys.argv[0]` 和 `sys.executable` 所在目录）→ 系统 PATH。
找不到抛 `FFmpegNotFoundError`，消息以「未找到视频处理组件，请重新安装软件」开头。`check()` 返回两个工具的路径、来源（env/bundled/path）和 `-version` 首行，
供 `dongai-backend --selfcheck`（缺失则 selfcheck 失败）和启动自检（缺失只在 stderr 告警，不阻止启动）使用。
打包：`desktop/build_backend.py --ffmpeg-dir <含 ffmpeg 和 ffprobe 的目录>` 复制到 `bin/`；目录里若有 `licenses/` 会复制到包内 `licenses/ffmpeg/`。
`electron-builder.yml` 的 `extraResources` 整体带走 `desktop/dist/dongai-backend`，`bin/` 自然包含在内，无需修改（macOS 签名时 L-09 需要把 `bin/ffmpeg`、`bin/ffprobe` 也纳入嵌套二进制签名）。

## 3. 可选来源与许可证（官方页面上看到的）

| 来源 | 平台 | 页面上的许可声明 | 是否带 GPL 组件 | 校验 |
|---|---|---|---|---|
| [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds)（ffmpeg.org 下载页列为 Windows 来源） | win64、linux64/arm64；**没有 macOS** | README 说明 `lgpl` 变体 "Lacking libraries that are GPL-only. Most prominently libx264 and libx265"；仓库自身是 MIT，页面未给出 LGPL 变体的许可证文本 | `gpl` 变体带；**`lgpl` 变体不带** x264/x265。`lgpl` 变体里是否带 libmp3lame [未验证，需下载后看 `ffmpeg -buildconf`] | 同 release 里有 `checksums.sha256`；资产名如 `ffmpeg-n9.0-latest-win64-lgpl-9.0.zip`、`...-lgpl-shared-9.0.zip`（见 [latest release](https://github.com/BtbN/FFmpeg-Builds/releases/tag/latest)） |
| [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)（essentials / full） | Windows x64 | 页面写 "All builds are licensed as GPLv3"；站点内容 CC BY-NC-ND 4.0 | **带**（essentials 含 x264、x265 等），**不能作为 LGPL 分发** | 提供 `.sha256` |
| [evermeet.cx](https://evermeet.cx/ffmpeg/)（ffmpeg.org 下载页列为 macOS 来源） | macOS **仅 Intel x64**，作者明确 "do not plan to provide native ffmpeg binaries for Apple Silicon" | 页面未写许可证，但 configure 带 `--enable-gpl --enable-version3`，即 GPLv3 构建 | **带**（libx264、libx265、libxvid 等） | 无 SHA256，只有 GPG 签名（key 0x476C4B611A660874） |
| 自行从源码构建（[ffmpeg.org 源码](https://ffmpeg.org/download.html)，当前 9.0.2） | 任意 | 不加 `--enable-gpl`/`--enable-nonfree` 即 LGPL（见 [legal](https://ffmpeg.org/legal.html)） | 由我们控制 | 源码包有 `.asc` 签名；Homebrew 公式里固定的 sha256 可作交叉核对（9.0.2: `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`） |
| Homebrew `ffmpeg` | macOS arm64/x64 | 通常 `--enable-gpl`（带 x264/x265），动态链接大量 dylib | 带 | 仅可作本机开发使用，**不可随包分发** |

要点：**现成的 macOS arm64 LGPL 静态构建，我没有找到可信的官方来源**；macOS arm64 与 x64 的 LGPL 版基本只能自己从官方源码编（外部库只要 libmp3lame）。Windows x64 可用 BtbN 的 `lgpl` 变体（需确认含 libmp3lame，否则需自编或改走别的 mp3 编码方案）。

## 4. 本调用点能否被 LGPL 构建满足

- 当前所有调用点：解码（原生）、PNG（原生）、MP3 编码（libmp3lame，LGPL 库）、滤镜（原生）。**LGPL 构建 + libmp3lame 即可满足，不需要 libx264**。
- 若将来需要 H.264 **软编**（拼接、导出成片、字幕烧录等）：libx264/libx265 是 GPL，LGPL 构建没有。替代：
  1. 系统硬件编码器：macOS `h264_videotoolbox`（LGPL 构建可启用）、Windows `h264_mf`（Media Foundation）/`h264_nvenc`/`h264_amf`/`h264_qsv`——依赖用户机器，质量/码控与 x264 不同；
  2. `libopenh264`（Cisco，BSD 许可；Cisco 提供二进制并承担 H.264 专利费，要求用其下载的二进制，**自编则不享受专利付费豁免**）[据我所知，需法务核对]；
  3. `mpeg4`（原生，LGPL，体积大画质差，剪映兼容性也差）、VP9/AV1（libvpx、libaom、SVT-AV1 为 BSD 类许可，但 mp4/剪映兼容性要另评估）；
  4. 把 GPL 的 x264 做成**独立可执行文件**由用户可选下载，而不是随包分发（GPL 的"聚合"边界需要法务判断）；
  5. 买商业授权（x264 有商业双许可）。
- 另有 **H.264/AAC 专利池**问题（独立于版权许可证）：随包分发编码器是否需要专利许可，需要法务/专利确认。当前只有解码和 MP3 编码，MP3 专利已于 2017 年到期 [我的理解]。

## 5. 分发 LGPL 构建需履行的义务（我的理解，来自 [ffmpeg legal 清单](https://ffmpeg.org/legal.html)）

1. 构建时不带 `--enable-gpl`、`--enable-nonfree`；不链接任何 GPL 库。
2. 提供与分发二进制**对应的** FFmpeg 源码（含我们的补丁 diff），放在与二进制同一网站，或随安装包；附 configure 命令行（`ffmpeg -buildconf`）的文本。
3. **允许用户替换**库：LGPL 要求用户能用修改版的库重新链接。官方清单建议动态链接（DLL/dylib）；静态单文件 ffmpeg 可执行文件是否满足存在争议，常见做法是随包用**独立的 ffmpeg 可执行文件**（作为独立程序通过命令行调用，与我们的程序是"聚合"关系，我们的代码不链接 libav）+ 提供可替换方式（`DONGAI_FFMPEG_BIN` 环境变量已具备）。这一点需要法务确认。
4. 在下载页、"关于"框、EULA 里声明使用 FFmpeg（LGPLv2.1）并给出源码链接；EULA 不得声称拥有 FFmpeg，不得禁止逆向工程（针对 LGPL 部分）。
5. 随包附 LGPL 许可证文本和 libmp3lame 等所含库的许可证（LAME 同为 LGPL，需重复以上要求）。构建脚本已支持 `--ffmpeg-dir/licenses/` 复制到 `licenses/ffmpeg/`。
6. 名称拼写 FFmpeg；不改混淆 DLL 名。

## 6. 需要你决定的事

1. **LGPL 构建的来源**：macOS arm64/x64 只能自编（我这次被拦下，没能在本机完成编译，见下）；Windows 用 BtbN lgpl 变体还是同样自编？谁来维护构建与源码托管？
2. **是否接受"独立可执行文件 + 环境变量可替换"作为满足 LGPL 的方式**（法务确认）。
3. 是否预期未来要 H.264 软编；若要，选哪条替代路线（上面 1~5）。
4. MP3 输出能否改为别的格式以去掉 libmp3lame 依赖（需前端/剪映兼容性评估）；不改则必须确认所选构建带 libmp3lame。

## 7. 本机验证记录

- 官方 macOS 渠道不可用：evermeet 仅 Intel 且是 GPL 构建，故没有下载。自编被自动模式拦截（"下载源码并执行 configure/make"），没有强行绕过；
  已下载 `ffmpeg-9.0.2.tar.xz` 到 `~/.local/dongai-build/ffmpeg/src/`，sha256 与 Homebrew 公式固定值一致。
- 打包机制用 Homebrew 的 ffmpeg/ffprobe（GPL 构建，动态链接，**仅限本机开发验证，不可分发**）经 `--ffmpeg-dir` 复制进包做了验证，结果：包内 `bin/ffmpeg`、`bin/ffprobe` 经 `--selfcheck` 识别为 bundled 并带版本；冒烟 8（lavfi 两段测试源 concat 为 mpeg4 mp4，ffprobe 时长 2.0 秒）通过。tts_mix 的 mp3 编码路径（libmp3lame）未用 LGPL 构建验证。
