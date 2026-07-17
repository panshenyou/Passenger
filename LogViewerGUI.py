import tkinter as tk
from tkinter import ttk
import time
import threading
import os
import sys
import re

# ====================== 全局配置参数 ======================
MAX_LOG_LINES = 60                 # 每个日志区域最大显示行数
RESUME_FOLLOW_DELAY = 3.0          # 手动滑动日志后，静置多久恢复自动滚动
LOG_FONT_SIZE = 8                  # 日志内容字体大小
TITLE_FONT_SIZE = 9                # 分区标题字体大小
LOG_POLL_INTERVAL = 0.2            # 日志文件读取轮询间隔(秒)
CHART_REFRESH_INTERVAL = 0.3       # 分时图表后台刷新间隔(秒)
CHART_PADDING = 30                 # 图表上下左右内边距
LINE_WIDTH = 0.8                   # 加粗线条，避免过细看不见
ABNORMAL_LOG_MIN_HEIGHT = 130       # 异常原因日志最小高度

# 悬浮信息提示窗配色
TIP_BG_COLOR = "#111111"
TIP_FG_COLOR = "#eeeeee"
TIP_BORDER_COLOR = "#666666"

# 分时图十字准星虚线样式
CROSS_LINE_COLOR = "#505050"       # 十字线颜色
CROSS_DASH_STYLE = (4, 4)          # 虚线间隔样式


# A股交易时间 换算为分钟数
MORNING_START = 570    # 09:30
MORNING_END = 690      # 11:30
AFTER_START = 780      # 13:00
AFTER_END = 900        # 15:00

# ====================== 日志文件路径配置 ======================

# 项目根目录
QMT_PROJECT_ROOT = r"C:\Users\15113\Desktop\QMT_Software\py_strategy"
SCRIPT_DIR = os.path.join(QMT_PROJECT_ROOT, "log")
# 日志名称与窗口区域映射
LOG_FILE_NAME_MAP = {
    "t1": "Log_PositionStock.txt",          # t1窗口：异动涨跌区日志
    "t2": "Log_CommonDrawdown.txt",        # t2窗口：冲高回落区日志
    "t3": "Log_StockStrengthYesterday.txt", # t3窗口：昨日筛选区(分时图数据源)
    "t4": "Log_VolPriceBreak.txt",          # t4窗口：量价齐升区日志
    "t5": "Log_StrongStock.txt",            # t5窗口：强势监控区日志
    "t6": "Log_AbnormalReason.txt"          # t6窗口：异动原因特殊监控区
}

# 拼接为绝对路径
LOG_FILE_MAP = {k: os.path.join(SCRIPT_DIR, v) for k, v in LOG_FILE_NAME_MAP.items()}

# ====================== 主界面监控面板类 ======================
class QuantLogPanel:
    def __init__(self, root):
        # 主窗口对象
        self.root = root
        self.root.title("监控面板")
        self.root.geometry("1200x720")    # 初始窗口大小
        self.root.resizable(True, True)   # 允许自由缩放窗口

        # 全局界面配色定义
        BG_COLOR = "#000000"              # 主背景黑色
        FG_COLOR = "#cccccc"              # 文字浅灰色
        CURSOR_COLOR = "#cccccc"
        CHART_BG = "#0a0a0a"              # 图表背景深色
        LINE_GRAY = "#888888"             # 量价突破线条灰色
        LINE_WHITE = "#ffffff"            # 冲高回落线条白色
        LINE_TOP20 = "#ec8a0b"            # 今成交Top20回撤线条橙色
        AXIS_COLOR = "#444444"            # 坐标轴颜色
        TEXT_CHART_COLOR = "#aaaaaa"      # 图表文字颜色

        # 绑定配色到实例
        self.BG_COLOR = BG_COLOR
        self.FG_COLOR = FG_COLOR
        self.CHART_BG = CHART_BG
        self.LINE_GRAY = LINE_GRAY
        self.LINE_WHITE = LINE_WHITE
        self.LINE_TOP20 = LINE_TOP20
        self.AXIS_COLOR = AXIS_COLOR
        self.TEXT_CHART_COLOR = TEXT_CHART_COLOR

        # 日志滚动状态标记
        self.manual_view = False          # 是否手动滑动日志
        self.last_scroll_time = 0         # 最后手动滑动时间戳

        # 文件读取偏移记录，实现增量读取日志
        self.file_read_pos = {k: 0 for k in LOG_FILE_MAP.keys()}

        # 程序运行总开关
        self.running_flag = True

        # 分时图数据源缓存列表 (分钟数, 时间字符串, 昨量价突破, 昨冲高回落, 今Top20最大回撤)
        self.chart_data = []

        # 悬浮提示窗相关变量
        self.tip_win = None
        self.tip_label = None

        # 十字准星画布标签
        self.cross_tag = "cross_line"
        self.mouse_in_chart = False       # 鼠标是否悬浮在图表内
        self.mouse_x = 0                  # 记录鼠标X坐标
        self.mouse_y = 0                  # 记录鼠标Y坐标

        # 图表绘图缓存参数
        self._chart_x_map = []
        self._get_x_pos_func = None
        self._get_y_range = (0, 0)
        self._inner_rect = (0, 0, 0, 0)

        # 设置主窗口背景
        self.root.configure(bg=BG_COLOR)

        # 美化滚动条样式
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TPanedWindow", background=BG_COLOR, borderwidth=0)
        style.configure("TScrollbar", background=BG_COLOR, troughcolor=BG_COLOR, borderwidth=0, relief=tk.FLAT)
        style.map("TScrollbar", background=[("active", BG_COLOR), ("pressed", BG_COLOR)])

        # ====================== 整体布局搭建 ======================
        self.main_pane = ttk.PanedWindow(root, orient=tk.VERTICAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # 上层左右双日志窗口
        self.top_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.top_pane, weight=2)

        # 左侧：异动涨跌区
        f1 = tk.Frame(self.top_pane, bg=BG_COLOR, bd=0)
        self.top_pane.add(f1, weight=1)
        tk.Label(f1, text="异动涨跌区", fg=FG_COLOR, bg=BG_COLOR,
                 font=("Consolas", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2)
        self.t1 = tk.Text(f1, font=("Consolas", LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s1 = ttk.Scrollbar(f1, command=self.t1.yview)
        s1.pack(side=tk.RIGHT, fill=tk.Y)
        self.t1.config(yscrollcommand=s1.set)

        # 右侧：冲高回落区
        f2 = tk.Frame(self.top_pane, bg=BG_COLOR, bd=0)
        self.top_pane.add(f2, weight=1)
        tk.Label(f2, text="冲高回落区", fg=FG_COLOR, bg=BG_COLOR,
                 font=("Consolas", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2)
        self.t2 = tk.Text(f2, font=("Consolas", LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s2 = ttk.Scrollbar(f2, command=self.t2.yview)
        s2.pack(side=tk.RIGHT, fill=tk.Y)
        self.t2.config(yscrollcommand=s2.set)

        # 中层左右双日志窗口
        self.mid_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.mid_pane, weight=2)

        # 左侧：昨日筛选区
        f3 = tk.Frame(self.mid_pane, bg=BG_COLOR, bd=0)
        self.mid_pane.add(f3, weight=1)
        tk.Label(f3, text="昨日筛选区(昨量价突破>-1%, 昨冲高回落>-2%, Top20>-3%)", fg=FG_COLOR, bg=BG_COLOR,
                 font=("Consolas", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2)
        self.t3 = tk.Text(f3, font=("Consolas", LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t3.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s3 = ttk.Scrollbar(f3, command=self.t3.yview)
        s3.pack(side=tk.RIGHT, fill=tk.Y)
        self.t3.config(yscrollcommand=s3.set)

        # 右侧：量价齐升区
        f4 = tk.Frame(self.mid_pane, bg=BG_COLOR, bd=0)
        self.mid_pane.add(f4, weight=1)
        tk.Label(f4, text="量价齐升区", fg=FG_COLOR, bg=BG_COLOR,
                 font=("Consolas", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2)
        self.t4 = tk.Text(f4, font=("Consolas", LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t4.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s4 = ttk.Scrollbar(f4, command=self.t4.yview)
        s4.pack(side=tk.RIGHT, fill=tk.Y)
        self.t4.config(yscrollcommand=s4.set)

        # 下层：左侧日志 + 右侧分时图
        bottom_main = tk.Frame(self.main_pane, bg=BG_COLOR)
        self.main_pane.add(bottom_main, weight=2)
        bottom_pane = ttk.PanedWindow(bottom_main, orient=tk.HORIZONTAL)
        bottom_pane.pack(fill=tk.BOTH, expand=True)

        # 左侧：强势监控日志
        left_log_frame = tk.Frame(bottom_pane, bg=BG_COLOR)
        bottom_pane.add(left_log_frame, weight=12)
        tk.Label(left_log_frame, text="强势监控区", fg=FG_COLOR, bg=BG_COLOR,
                 font=("Consolas", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2)
        self.t5 = tk.Text(left_log_frame, font=("Consolas", LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t5.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s5 = ttk.Scrollbar(left_log_frame, command=self.t5.yview)
        s5.pack(side=tk.RIGHT, fill=tk.Y)
        self.t5.config(yscrollcommand=s5.set)

        # 右侧：分时图画布
        chart_frame = tk.Frame(bottom_pane, bg=BG_COLOR)
        bottom_pane.add(chart_frame, weight=10)
        tk.Label(chart_frame, text="昨筛选强度分时图(灰线=昨量价突破 白线=昨冲高回落 橙线=今成交Top20平均最大回撤)",
                 fg=FG_COLOR, bg=BG_COLOR, font=("Consolas", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2)
        self.chart_canvas = tk.Canvas(chart_frame, bg=CHART_BG, bd=0, highlightthickness=0)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chart_canvas.bind("<Configure>", self.on_chart_resize)

        # 最底部：异动原因特殊监控区
        abnormal_frame = tk.Frame(self.main_pane, bg=BG_COLOR, height=ABNORMAL_LOG_MIN_HEIGHT)
        self.main_pane.add(abnormal_frame, weight=0)
        abnormal_frame.pack_propagate(False)

        tk.Label(abnormal_frame, text="通义千问异动原因", fg=FG_COLOR, bg=BG_COLOR,
                 font=("Consolas", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2)
        self.t6 = tk.Text(abnormal_frame, font=("Consolas", LOG_FONT_SIZE), bg="#050505", fg=FG_COLOR,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t6.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s6 = ttk.Scrollbar(abnormal_frame, command=self.t6.yview)
        s6.pack(side=tk.RIGHT, fill=tk.Y)
        self.t6.config(yscrollcommand=s6.set)

        # 绑定事件
        self.bind_scroll_event()
        self.bind_drag_event()
        self.start_file_monitor_threads()
        self.start_chart_refresh_loop()

        self.chart_canvas.bind("<Enter>", self.on_chart_enter)
        self.chart_canvas.bind("<Motion>", self.on_chart_mouse_move)
        self.chart_canvas.bind("<Leave>", self.on_chart_leave)

        self.root.after(200, self.draw_chart)

    # ====================== 工具方法 ======================
    def time_to_minute(self, time_str):
        """时分字符串转为当日分钟数 09:30 -> 570"""
        h, m = map(int, time_str.split(":"))
        return h * 60 + m

    # ========== 【重点修复】新版日志数据解析函数 ==========
    def parse_log_chart_data(self, log_content):
        res = []
        lines = log_content.splitlines()
        temp_dict = {}

        # 正则简化通用匹配
        time_reg = re.compile(r'(\d{2}:\d{2})')
        break_reg = re.compile(r'昨量价突破.*?([+-]?\d+\.?\d+)%')
        fall_reg = re.compile(r'昨冲高回落.*?([+-]?\d+\.?\d+)%')
        top20_reg = re.compile(r'Top20.*?([+-]?\d+\.?\d+)%')

        curr_time = None
        brk_val = None
        fall_val = None
        top_val = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 优先提取时间
            t_match = time_reg.search(line)
            if t_match:
                # 上一组数据存起来
                if curr_time and brk_val is not None and fall_val is not None and top_val is not None:
                    temp_dict[curr_time] = (brk_val, fall_val, top_val)
                # 重置新时间
                curr_time = t_match.group(1)
                brk_val = fall_val = top_val = None

            # 依次匹配三类数值
            bm = break_reg.search(line)
            if bm:
                brk_val = float(bm.group(1))
            fm = fall_reg.search(line)
            if fm:
                fall_val = float(fm.group(1))
            tm = top20_reg.search(line)
            if tm:
                top_val = float(tm.group(1))

        # 存入最后一组
        if curr_time and brk_val is not None and fall_val is not None and top_val is not None:
            temp_dict[curr_time] = (brk_val, fall_val, top_val)

        # 转为标准数据格式
        for tm_str, (b, f, t) in temp_dict.items():
            minute = self.time_to_minute(tm_str)
            if MORNING_START <= minute <= AFTER_END:
                res.append((minute, tm_str, b, f, t))

        # 时序排序去重
        res.sort(key=lambda x: x[0])
        return res

    def update_chart_cache(self, new_data_list):
        """更新图表缓存，去重并保留完整时序数据"""
        if not new_data_list:
            return
        exist_keys = set((d[0], d[1]) for d in self.chart_data)
        for item in new_data_list:
            if (item[0], item[1]) not in exist_keys:
                self.chart_data.append(item)
        self.chart_data.sort(key=lambda x: x[0])

    # ====================== 分时图绘制核心 ======================
    def draw_chart(self):
        canvas = self.chart_canvas
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw < 50 or ch < 50:
            canvas.delete("all")
            return
        pad = CHART_PADDING
        inner_w = cw - pad * 2
        inner_h = ch - pad * 2

        morning_start = MORNING_START
        morning_end = MORNING_END
        after_start = AFTER_START
        after_end = AFTER_END
        total_valid_min = (morning_end - morning_start) + (after_end - after_start)

        def time_to_valid_x(t_val):
            if morning_start <= t_val <= morning_end:
                offset = t_val - morning_start
            elif after_start <= t_val <= after_end:
                offset = (morning_end - morning_start) + (t_val - after_start)
            else:
                offset = 0 if t_val < morning_start else total_valid_min
            return pad + (offset / total_valid_min) * inner_w

        # 值域适配
        if not self.chart_data:
            min_y, max_y = -5, 5
        else:
            y_break = [d[2] for d in self.chart_data]
            y_fall = [d[3] for d in self.chart_data]
            y_top20 = [d[4] for d in self.chart_data]
            y_all = y_break + y_fall + y_top20
            min_y, max_y = min(y_all), max(y_all)
            ry = max_y - min_y
            min_y -= ry * 0.15
            max_y += ry * 0.15
            if abs(ry) < 0.2:
                min_y -= 2
                max_y += 2

        def v2y(v):
            return ch - pad - (v - min_y) / (max_y - min_y) * inner_h

        canvas.delete("chart_item")

        # 坐标轴
        canvas.create_line(pad, pad, pad, ch-pad, fill=self.AXIS_COLOR, width=1, tag="chart_item")
        canvas.create_line(pad, ch-pad, cw-pad, ch-pad, fill=self.AXIS_COLOR, width=1, tag="chart_item")

        # X时间刻度
        time_ticks = [(morning_start, "09:30"),(morning_end, "11:30"),(after_start, "13:00"),(after_end, "15:00")]
        for tm_val, txt in time_ticks:
            px = time_to_valid_x(tm_val)
            canvas.create_text(px, ch-pad+12, text=txt, fill=self.TEXT_CHART_COLOR, font=("Consolas",7), tag="chart_item")

        # Y轴网格
        y_step = (max_y - min_y) / 5
        for i in range(6):
            yv = min_y + y_step * i
            yp = v2y(yv)
            canvas.create_line(pad, yp, cw-pad, yp, fill="#222222", width=1, tag="chart_item")
            canvas.create_text(pad-5, yp, text=f"{yv:.1f}", fill=self.TEXT_CHART_COLOR, font=("Consolas",7), anchor=tk.E, tag="chart_item")

        # 零轴
        zero_y = v2y(0)
        if pad < zero_y < ch-pad:
            canvas.create_line(pad, zero_y, cw-pad, zero_y, fill="#555555", width=1, dash=(2,2), tag="chart_item")

        # 三条曲线强制渲染
        if len(self.chart_data) >= 2:
            # 灰线
            pts = [(time_to_valid_x(d[0]), v2y(d[2])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_GRAY, width=LINE_WIDTH, tag="chart_item")
            # 白线
            pts = [(time_to_valid_x(d[0]), v2y(d[3])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_WHITE, width=LINE_WIDTH, tag="chart_item")
            # 橙线
            pts = [(time_to_valid_x(d[0]), v2y(d[4])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_TOP20, width=LINE_WIDTH, tag="chart_item")

        self._chart_x_map = [(time_to_valid_x(d[0]), d) for d in self.chart_data]
        self._get_x_pos_func = time_to_valid_x
        self._get_y_range = (min_y, max_y)
        self._inner_rect = (pad, ch-pad, cw-pad, pad)

        # ===================== 靠近触发点底部提示+边框+指向箭头 =====================
        first_risk_pos = None
        for data in self.chart_data:
            top20_dd = data[4]
            if top20_dd < -3.0:
                first_risk_pos = data
                break

        if first_risk_pos:
            # 风险点位坐标
            risk_x = time_to_valid_x(first_risk_pos[0])
            risk_y = v2y(first_risk_pos[4])

            # 点位小红点标记
            canvas.create_oval(
                risk_x-3, risk_y-3, risk_x+3, risk_y+3,
                fill="#ff3333", outline="#ff6666", tag="chart_item"
            )

            # 提示文字X坐标和触发点对齐，Y固定在图表最下方内侧
            tip_x = risk_x
            tip_y = ch - 18
            warn_text = f"勿接力！切新题材！"

            # 带红色细边框，透明内部底色
            txt_w = 100
            txt_h = 16
            canvas.create_rectangle(
                tip_x - txt_w/2 - 4, tip_y - txt_h/2 - 2,
                tip_x + txt_w/2 + 4, tip_y + txt_h/2 + 2,
                fill="", outline="#ff4444", width=1, dash=(3,3), tag="chart_item"
            )

            # 警示文字
            canvas.create_text(
                tip_x, tip_y,
                text=warn_text,
                fill="#ff5555",
                font=("微软雅黑", 8, "bold"),
                anchor=tk.CENTER,
                tag="chart_item"
            )

            # 直线箭头从底部提示框向上指向破位点
            canvas.create_line(
                tip_x, tip_y - txt_h/2 - 2,
                risk_x, risk_y + 3,
                fill="#ff4444", width=1.2, dash=(3,3), arrow=tk.FIRST, tag="chart_item"
            )
        # =====================================================================

        if self.mouse_in_chart:
            self.draw_cross_line(self.mouse_x, self.mouse_y)

    def draw_cross_line(self, x, y):
        pad, bottom, right, top = self._inner_rect
        self.chart_canvas.delete(self.cross_tag)
        if pad < x < right and top < y < bottom:
            self.chart_canvas.create_line(x, top, x, bottom, fill=CROSS_LINE_COLOR,dash=CROSS_DASH_STYLE, width=1, tag=self.cross_tag)
            self.chart_canvas.create_line(pad, y, right, y, fill=CROSS_LINE_COLOR,dash=CROSS_DASH_STYLE, width=1, tag=self.cross_tag)

    # ====================== 图表鼠标事件 ======================
    def on_chart_enter(self, event):
        self.mouse_in_chart = True
        self.mouse_x = event.x
        self.mouse_y = event.y
        if self.tip_win is not None:
            return
        self.tip_win = tk.Toplevel(self.root)
        self.tip_win.overrideredirect(True)
        self.tip_win.attributes("-topmost", True)
        self.tip_win.configure(bg=TIP_BG_COLOR)
        self.tip_label = tk.Label(self.tip_win, text="", bg=TIP_BG_COLOR, fg=TIP_FG_COLOR,font=("Consolas", 8), justify=tk.LEFT)
        self.tip_label.pack(ipadx=6, ipady=3)
        self.draw_cross_line(event.x, event.y)

    def on_chart_mouse_move(self, event):
        if self.tip_win is None:
            return
        self.mouse_x = event.x
        self.mouse_y = event.y
        x, y = event.x, event.y
        pad, bottom, right, top = self._inner_rect
        self.draw_cross_line(x, y)

        if not self._chart_x_map or not (pad < x < right and top < y < bottom):
            return
        near_data = None
        min_dis = 9999
        for px, data in self._chart_x_map:
            dis = abs(px - x)
            if dis < min_dis:
                min_dis = dis
                near_data = data
        if not near_data or min_dis > 20:
            return

        _, hhmm, break_rate, fall_rate, top20_dd = near_data
        text = (f"时间：{hhmm}\n"
                f"昨量价突破：{break_rate:.2f}%\n"
                f"昨冲高回落：{fall_rate:.2f}%\n"
                f"今Top20最大回撤：{top20_dd:.2f}%")
        self.tip_label.config(text=text)

        win_x = self.chart_canvas.winfo_rootx() + x + 15
        win_y = self.chart_canvas.winfo_rooty() + y + 15
        w, h = 140, 65
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if win_x + w > sw:
            win_x = self.chart_canvas.winfo_rootx() + x - w - 15
        if win_y + h > sh:
            win_y = self.chart_canvas.winfo_rooty() + y - h - 15
        self.tip_win.geometry(f"{w}x{h}+{win_x}+{win_y}")

    def on_chart_leave(self, event):
        self.mouse_in_chart = False
        if self.tip_win is not None:
            self.tip_win.destroy()
            self.tip_win = None
            self.tip_label = None
        self.chart_canvas.delete(self.cross_tag)

    def on_chart_resize(self, event):
        self.draw_chart()

    def start_chart_refresh_loop(self):
        def loop():
            while self.running_flag:
                time.sleep(CHART_REFRESH_INTERVAL)
                self.root.after_idle(self.draw_chart)
        threading.Thread(target=loop, daemon=True).start()

    # ====================== 日志窗口功能 ======================
    def limit_log_lines(self, text_widget):
        cnt = int(text_widget.index(tk.END).split('.')[0])
        if cnt > MAX_LOG_LINES:
            text_widget.delete("1.0", f"{cnt-MAX_LOG_LINES}.0")

    def bind_scroll_event(self):
        boxes = [self.t1, self.t2, self.t3, self.t4, self.t5, self.t6]
        def cb(e):
            self.manual_view = True
            self.last_scroll_time = time.time()
        for b in boxes:
            b.bind("<MouseWheel>", cb)

    def safe_append_log(self, wd, msg):
        def inner():
            t = time.strftime("%H:%M:%S")
            wd.insert(tk.END, f"[{t}] {msg}\n")
            self.limit_log_lines(wd)
            if self.manual_view and time.time()-self.last_scroll_time > RESUME_FOLLOW_DELAY:
                self.manual_view = False
            if not self.manual_view:
                wd.see(tk.END)
        self.root.after_idle(inner)

    def bind_drag_event(self):
        def start(_):
            for w in [self.t1, self.t2, self.t3, self.t4, self.t5, self.t6]:
                w.config(state=tk.DISABLED)
        def end(_):
            for w in [self.t1, self.t2, self.t3, self.t4, self.t5, self.t6]:
                w.config(state=tk.NORMAL)
        for p in [self.top_pane, self.mid_pane, self.main_pane]:
            p.bind("<ButtonPress-1>", start)
            p.bind("<ButtonRelease-1>", end)

    def log_warn(self, msg):self.safe_append_log(self.t1, msg)
    def log_strong(self, msg):self.safe_append_log(self.t2, msg)
    def log_market(self, msg):self.safe_append_log(self.t3, msg)
    def log_position(self, msg):self.safe_append_log(self.t4, msg)
    def log_system(self, msg):self.safe_append_log(self.t5, msg)
    def log_abnormal(self, msg):self.safe_append_log(self.t6, msg)

    def get_text_widget(self, k):
        m = {"t1":self.t1,"t2":self.t2,"t3":self.t3,"t4":self.t4,"t5":self.t5,"t6":self.t6}
        return m.get(k)

    def single_file_monitor(self, key, path):
        pos = self.file_read_pos[key]
        wd = self.get_text_widget(key)
        while self.running_flag:
            try:
                if not os.path.exists(path):
                    time.sleep(LOG_POLL_INTERVAL)
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    lines = f.readlines()
                    pos = f.tell()
                    self.file_read_pos[key] = pos
                if lines:
                    cont = "".join(lines)
                    # 只解析昨日筛选日志
                    if key == "t3":
                        arr = self.parse_log_chart_data(cont)
                        self.update_chart_cache(arr)
                    # 更新日志面板
                    def ui_up():
                        wd.insert(tk.END, cont)
                        self.limit_log_lines(wd)
                        if self.manual_view and time.time()-self.last_scroll_time > RESUME_FOLLOW_DELAY:
                            self.manual_view = False
                        if not self.manual_view:
                            wd.see(tk.END)
                    self.root.after_idle(ui_up)
            except Exception as e:
                pass
            time.sleep(LOG_POLL_INTERVAL)

    def start_file_monitor_threads(self):
        for k, p in LOG_FILE_MAP.items():
            threading.Thread(target=self.single_file_monitor, args=(k, p), daemon=True).start()

    def close_all_monitor(self):
        self.running_flag = False
        if self.tip_win:
            self.tip_win.destroy()
        self.chart_canvas.delete(self.cross_tag)


# ====================== 程序入口 ======================
if __name__ == "__main__":
    root = tk.Tk()
    app = QuantLogPanel(root)

    def on_close():
        app.close_all_monitor()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\n[INFO] 收到键盘中断，正在退出程序...")
        on_close()