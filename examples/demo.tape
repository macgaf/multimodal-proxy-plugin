# multimodal-proxy demo 录制脚本
# 安装 vhs 后运行: vhs examples/demo.tape
# 产物: examples/demo.gif
#
# 安装 vhs: brew install vhs (macOS)

Output examples/demo.gif

Set FontSize 14
Set Width 900
Set Height 500
Set Padding 20

Type "cd multimodal-proxy-plugin"
Enter
Sleep 500ms

Type "bash scripts/demo.sh"
Enter
Sleep 8s
