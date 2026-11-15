# NASAPic

用 Python 抓取 NASA 的 [Astronomy Picture of the Day](https://science.nasa.gov/apod/)。每天发布的内容可能是一张天文照片，也可能是一段视频。可以在这里看最近几期，也可以把图片下载到本地。

## NASA 每日天文图 · 最近 7 期

<!-- apod-week:start -->
<!-- apod-week:end -->

图集按 NASA 发布日期倒序排列。点击缩略图可打开大图，点击标题可看 NASA 的原文说明与署名。视频期会链接到原文，有封面时也会显示预览。图片尺寸来自实际文件，长边达到 3840 像素且短边达到 2160 像素时会标出 4K。

## 本地下载

需要 Python 3.10 或更新版本。运行以下命令会回查最近 5 期，把图片保存到 `downloads/`，已有的图片会跳过。

```shell
python -m pip install -r requirements.txt
python apod.py download
```

只下载指定日期时可以加 `--date`，用 `--output` 指定保存目录。

```shell
python apod.py download --date 2026-11-15 --output downloads
```

## 自动更新

GitHub Actions 每天北京时间 **20:37** 检查 NASA Science 的 APOD 数据。有变化时提交 README 和最近 7 期的缩略图。也可以在 [Actions](https://github.com/LittleCabbage-00/NASAPic/actions/workflows/apod.yml) 手动运行，无需配置 API Key。

图片及视频的署名与使用条款见 NASA 的各期原文和 [APOD FAQ](https://apod.nasa.gov/rjn/apod/ap_faq.html)。
