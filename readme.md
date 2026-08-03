# Android自动化操作工具

## 一、功能介绍

- 输入：一系列操作序列
- 输出：输入操作序列得到的PerfDog性能文件（URL）

<br>

## 二、前置条件

- 下载perfDog Service： https://perfdog.qq.com/perfdogservice
- 确保系统中下载了adb工具
- Android真机开启开发者模式、打开USB调试、打开USB调试(安全设置)，以允许模拟点击

<br>

## 三、环境配置

- python环境，用于支持PerfDog Service
```shell
cd <当前项目根目录>
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install grpcio protobuf
```

- PerfDog Service config配置

配置不写在代码里。复制模板后填入自己的 token 与路径：
```shell
cp local_env/.env.example local_env/.env
```
编辑 `local_env/.env`（该目录已被 .gitignore 忽略，不会入库）：
```txt
SERVICE_TOKEN = '<PerfDog 申请到的 token>'
SERVICE_PATH  = '<PerfDogService 可执行文件路径>'
PD_PACKAGE    = '<被测 App 包名>'
PD_DEVICE     = ''            # 留空则自动探测唯一在线设备
```

<br>

## 三、Get Start

### 一、录制个人UI操作序列

最简使用指南，以微信首页进入直播间、并回到首页为例
```shell
./record.sh start wechat_enter_live.actions
```

录制出的actions文件如下
```txt
# 由 wechat_enter_live.log 生成  屏幕 1220x2656  原始量程 121999x265599
# 手势数 7
tap 792 2548
sleep 5
tap 148 746
sleep 5
tap 397 1968
sleep 10
tap 1142 178
sleep 5
tap 773 2340
sleep 3
tap 88 223
sleep 3
tap 180 2519
```
考虑每次操作的延迟，可以适当增加sleep时间

<br>

**具体使用详见[record.sh](record.sh)**

### 二、pipeline执行自动化操作、输出PerfDog性能文件

**前置条件：有了actions文件，即操作序列**

最简单的pipeline执行方式，直接执行自己录制的actions文件
```shell
./pipeline.sh wechat_enter_live
```

跑完会在末尾直接输出报告地址：
```txt
============================================================
用例名   : wechat_enter_live_x1_0803_095849
性能报告 : https://perfdog.qq.com/case_detail/12035743
============================================================
```

CI 场景可用 `--url-file out.txt` 把 URL 单独写入文件。

<br>

## 四、不足、后续规划

- [ ] PipeLine的监控数据需要根据具体情况，支持动态调整
- [ ] 由Android平台拓展到其他平台
- [ ] 收集反馈意见

<br>

## 五、其他文档

**更详细的项目文档请参考[usage.md](docs/usage.md)(agent总结生成的)**

---

## 参考

- adb官方文档：https://developer.android.com/tools/adb?hl=zh-cn
- PerfDog Service 自动化文档：https://perfdog.qq.com/article_detail?id=10143&issue_id=0&plat_id=2
- PerfDog Service 自动化 Demo：https://github.com/perfdog/perfdog-service-demo-v2/blob/master/readme_zh.md