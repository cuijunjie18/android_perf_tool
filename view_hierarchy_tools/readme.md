# 视图层级获取工具

## Demo

- 查看当前resume的activity
```shell
adb shell dumpsys window windows | grep mResumeActivity
adb shell dumpsys activity activities | grep ResumedActivity
```

- 通过activity获取视图层级
```shell
adb shell dumpsys activity top > activity_top.txt
adb shell dumpsys activity 包名/完整Activity类名 > activity_top.txt
```