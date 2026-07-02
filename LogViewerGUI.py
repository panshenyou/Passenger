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
LINE_WIDTH = 0.5                   # 行情线条统一宽度

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
# 获取当前脚本所在目录，所有日志文件统一存放在同级目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

# 日志名称与窗口区域映射
LOG_FILE_NAME_MAP = {
    "t1": "Log_PositionStock.txt",          # t1窗口：持仓监控区日志
    "t2": "Log_CommonDrawdown.txt",        # t2窗口：冲高回落区日志
    "t3": "Log_StockStrengthYesterday.txt", # t3窗口：昨日筛选区(分时图数据源)
    "t4": "Log_VolPriceBreak.txt",          # t4窗口：量价齐升区日志
    "t5": "Log_StrongStock.txt"            # t5窗口：强势监控区日志
}

# 拼接为绝对路径
LOG_FILE_MAP = {k: os.path.join(SCRIPT_DIR, v) for k, v in LOG_FILE_NAME_MAP.items()}

# 数据正则表达式(预留)
DATA_PATTERN = re.compile(r'\[(\d{2}:\d{2})\]\s*([\d.-]+),([\d.-]+)')

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
        AXIS_COLOR = "#444444"            # 坐标轴颜色
        TEXT_CHART_COLOR = "#aaaaaa"      # 图表文字颜色

        # 绑定配色到实例
        self.BG_COLOR = BG_COLOR
        self.FG_COLOR = FG_COLOR
        self.CHART_BG = CHART_BG
        self.LINE_GRAY = LINE_GRAY
        self.LINE_WHITE = LINE_WHITE
        self.AXIS_COLOR = AXIS_COLOR
        self.TEXT_CHART_COLOR = TEXT_CHART_COLOR

        # 日志滚动状态标记
        self.manual_view = False          # 是否手动滑动日志
        self.last_scroll_time = 0         # 最后手动滑动时间戳

        # 文件读取偏移记录，实现增量读取日志
        self.file_read_pos = {k: 0 for k in LOG_FILE_MAP.keys()}

        # 程序运行总开关
        self.running_flag = True

        # 分时图数据源缓存列表
        self.chart_data = []

        # 悬浮提示窗相关变量
        self.tip_win = None
        self.tip_label = None

        # 十字准星画布标签
        self.cross_tag = "cross_line"
        self.mouse_in_chart = False       # 鼠标是否悬浮在图表内
        self.mouse_x = 0                  # 记录鼠标X坐标
        self.mouse_y = 0                  # 记录鼠标Y坐标

        # 设置主窗口背景
        self.root.configure(bg=BG_COLOR)

        # 美化滚动条样式
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TPanedWindow", background=BG_COLOR, borderwidth=0)
        style.configure("TScrollbar", background=BG_COLOR, troughcolor=BG_COLOR, borderwidth=0, relief=tk.FLAT)
        style.map("TScrollbar", background=[("active", BG_COLOR), ("pressed", BG_COLOR)])

        # ====================== 整体布局搭建 ======================
        # 垂直大布局：上两层日志 + 下层日志+图表
        self.main_pane = ttk.PanedWindow(root, orient=tk.VERTICAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # -------- 上层左右双日志窗口 --------
        self.top_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.top_pane, weight=2)

        # 左侧：持仓监控区
        f1 = tk.Frame(self.top_pane, bg=BG_COLOR, bd=0)
        self.top_pane.add(f1, weight=1)
        tk.Label(f1, text="持仓监控区", fg=FG_COLOR, bg=BG_COLOR,
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

        # -------- 中层左右双日志窗口 --------
        self.mid_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.mid_pane, weight=2)

        # 左侧：昨日筛选区
        f3 = tk.Frame(self.mid_pane, bg=BG_COLOR, bd=0)
        self.mid_pane.add(f3, weight=1)
        tk.Label(f3, text="昨日筛选区", fg=FG_COLOR, bg=BG_COLOR,
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

        # -------- 下层：左侧日志 + 右侧分时图 --------
        bottom_main = tk.Frame(self.main_pane, bg=BG_COLOR)
        self.main_pane.add(bottom_main, weight=2)
        bottom_pane = ttk.PanedWindow(bottom_main, orient=tk.HORIZONTAL)
        bottom_pane.pack(fill=tk.BOTH, expand=True)

        # 左侧：强势监控日志
        left_log_frame = tk.Frame(bottom_pane, bg=BG_COLOR)
        bottom_pane.add(left_log_frame, weight=1)
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
        bottom_pane.add(chart_frame, weight=1)
        tk.Label(chart_frame, text="昨筛选强度分时图(灰线=昨量价突破 白线=昨冲高回落)",
                 fg=FG_COLOR, bg=BG_COLOR, font=("Consolas", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2)
        self.chart_canvas = tk.Canvas(chart_frame, bg=CHART_BG, bd=0, highlightthickness=0)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chart_canvas.bind("<Configure>", self.on_chart_resize)  # 窗口缩放重绘图表

        # 绑定各类事件
        self.bind_scroll_event()        # 日志手动滚动事件
        self.bind_drag_event()          # 分割栏拖拽事件
        self.start_file_monitor_threads()# 启动日志监听线程
        self.start_chart_refresh_loop()  # 启动图表刷新线程

        # 绑定图表鼠标事件(十字线+悬浮提示)
        self.chart_canvas.bind("<Enter>", self.on_chart_enter)
        self.chart_canvas.bind("<Motion>", self.on_chart_mouse_move)
        self.chart_canvas.bind("<Leave>", self.on_chart_leave)

    # ====================== 工具方法 ======================
    def time_to_minute(self, time_str):
        """时分字符串转为当日分钟数 09:30 -> 570"""
        h, m = map(int, time_str.split(":"))
        return h * 60 + m

    def parse_log_chart_data(self, log_content):
        """
        解析昨日筛选区日志文本
        提取时间、量价突破平均涨幅、冲高回落平均涨幅
        返回结构化数据列表
        """
        res = []
        lines = log_content.splitlines()
        curr_hhmm = None        # 当前行时间
        avg_break_val = None    # 量价突破均值
        avg_fall_val = None     # 冲高回落均值

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 匹配日志头部时间行
            time_pat = re.compile(r'(\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2}))')
            time_match = time_pat.search(line)
            if time_match:
                curr_hhmm = time_match.group(2)
                continue

            # 匹配量价突破平均涨幅
            break_pat = re.compile(r'【昨量价突破组】.*?平均涨幅[:：]\s*([+-]?\d+\.?\d*)%')
            bm = break_pat.search(line)
            if bm and curr_hhmm:
                avg_break_val = float(bm.group(1))
                continue

            # 匹配冲高回落平均涨幅
            fall_pat = re.compile(r'【昨冲高回落组】.*?平均涨幅[:：]\s*([+-]?\d+\.?\d*)%')
            fm = fall_pat.search(line)
            if fm and curr_hhmm:
                avg_fall_val = float(fm.group(1))
                # 两组数据齐全则存入列表
                if avg_break_val is not None and avg_fall_val is not None:
                    minute = self.time_to_minute(curr_hhmm)
                    # 只保留交易时段数据，过滤午休
                    if (MORNING_START <= minute <= MORNING_END) or (AFTER_START <= minute <= AFTER_END):
                        res.append((minute, curr_hhmm, avg_break_val, avg_fall_val))
                    # 重置等待下一组数据
                    curr_hhmm = None
                    avg_break_val = None
                    avg_fall_val = None
        # 按时间升序排序
        return sorted(res, key=lambda x: x[0])

    def update_chart_cache(self, new_data_list):
        """更新图表缓存，去重并限制最大数据量"""
        exist_keys = set((d[0], d[1]) for d in self.chart_data)
        for item in new_data_list:
            if (item[0], item[1]) not in exist_keys:
                self.chart_data.append(item)
        # 最多保留300条历史数据
        if len(self.chart_data) > 300:
            self.chart_data = self.chart_data[-300:]

    # ====================== 分时图绘制核心 ======================
    def draw_chart(self):
        """绘制分时走势图，只刷新行情元素，保留十字准星"""
        canvas = self.chart_canvas
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw < 50 or ch < 50:
            canvas.delete("all")
            return
        pad = CHART_PADDING
        inner_w = cw - pad * 2
        inner_h = ch - pad * 2

        # 全天有效交易总时长
        total_valid_len = (MORNING_END - MORNING_START) + (AFTER_END - AFTER_START)

        # 自动计算Y轴上下限
        if not self.chart_data:
            min_y, max_y = -3, 3
        else:
            y_all = [d[2] for d in self.chart_data] + [d[3] for d in self.chart_data]
            min_y, max_y = min(y_all), max(y_all)
            ry = max_y - min_y
            min_y -= ry * 0.15
            max_y += ry * 0.15
            if abs(ry) < 0.1:
                min_y -= 1
                max_y += 1

        # 只删除行情标签元素，不删除十字线
        canvas.delete("chart_item")

        # 绘制XY主轴
        canvas.create_line(pad, pad, pad, ch-pad, fill=self.AXIS_COLOR, width=1, tag="chart_item")
        canvas.create_line(pad, ch-pad, cw-pad, ch-pad, fill=self.AXIS_COLOR, width=1, tag="chart_item")

        # 时间转画布X坐标（跳过午休空白区域）
        def get_x_pos(min_val):
            if MORNING_START <= min_val <= MORNING_END:
                offset = min_val - MORNING_START
            else:
                offset = (MORNING_END - MORNING_START) + (min_val - AFTER_START)
            return pad + (offset / total_valid_len) * inner_w

        # 涨跌幅转画布Y坐标
        def get_y_pos(val):
            return ch - pad - ((val - min_y) / (max_y - min_y)) * inner_h

        # 绘制早盘下午分割虚线
        split_x = get_x_pos(MORNING_END)
        canvas.create_line(split_x, pad, split_x, ch-pad, fill="#333333", width=1, dash=(3,3), tag="chart_item")

        # X轴时间刻度
        tick_list = [(MORNING_START, "09:30"), (MORNING_END, "11:30"),
                     (AFTER_START, "13:00"), (AFTER_END, "15:00")]
        for tm_val, txt in tick_list:
            px = get_x_pos(tm_val)
            canvas.create_text(px, ch-pad+12, text=txt, fill=self.TEXT_CHART_COLOR, font=("Consolas",7), tag="chart_item")

        # Y轴涨跌幅网格线
        y_step = (max_y - min_y) / 5
        for i in range(6):
            yv = min_y + y_step * i
            yp = get_y_pos(yv)
            canvas.create_line(pad, yp, cw-pad, yp, fill="#222222", width=1, tag="chart_item")
            canvas.create_text(pad-5, yp, text=f"{yv:.1f}", fill=self.TEXT_CHART_COLOR, font=("Consolas",7), anchor=tk.E, tag="chart_item")

        # 0涨幅基准线
        zero_y = get_y_pos(0)
        if pad < zero_y < ch-pad:
            canvas.create_line(pad, zero_y, cw-pad, zero_y, fill="#555555", width=1, dash=(2,2), tag="chart_item")

        # 绘制灰色量价突破走势线
        if len(self.chart_data)>=2:
            pts1 = [(get_x_pos(d[0]), get_y_pos(d[2])) for d in self.chart_data]
            for i in range(len(pts1)-1):
                x1,y1=pts1[i]
                x2,y2=pts1[i+1]
                canvas.create_line(x1,y1,x2,y2, fill=self.LINE_GRAY, width=LINE_WIDTH, tag="chart_item")

        # 绘制白色冲高回落走势线
        if len(self.chart_data)>=2:
            pts2 = [(get_x_pos(d[0]), get_y_pos(d[3])) for d in self.chart_data]
            for i in range(len(pts2)-1):
                x1,y1=pts2[i]
                x2,y2=pts2[i+1]
                canvas.create_line(x1,y1,x2,y2, fill=self.LINE_WHITE, width=LINE_WIDTH, tag="chart_item")

        # 缓存坐标映射，用于鼠标拾取数据
        self._chart_x_map = [(get_x_pos(d[0]), d) for d in self.chart_data]
        self._get_x_pos_func = get_x_pos
        self._get_y_range = (min_y, max_y)
        self._inner_rect = (pad, ch-pad, cw-pad, pad)

        # 重绘完成后恢复十字准星
        if self.mouse_in_chart:
            self.draw_cross_line(self.mouse_x, self.mouse_y)

    def draw_cross_line(self, x, y):
        """单独绘制十字准星虚线"""
        pad, bottom, right, top = self._inner_rect
        self.chart_canvas.delete(self.cross_tag)
        # 仅在图表有效区域内绘制
        if pad < x < right and top < y < bottom:
            # 垂直竖线
            self.chart_canvas.create_line(x, top, x, bottom, fill=CROSS_LINE_COLOR,
                                          dash=CROSS_DASH_STYLE, width=1, tag=self.cross_tag)
            # 水平横线
            self.chart_canvas.create_line(pad, y, right, y, fill=CROSS_LINE_COLOR,
                                          dash=CROSS_DASH_STYLE, width=1, tag=self.cross_tag)

    # ====================== 图表鼠标事件 ======================
    def on_chart_enter(self, event):
        """鼠标进入图表区域"""
        self.mouse_in_chart = True
        self.mouse_x = event.x
        self.mouse_y = event.y
        # 创建悬浮信息窗
        if self.tip_win is not None:
            return
        self.tip_win = tk.Toplevel(self.root)
        self.tip_win.overrideredirect(True)
        self.tip_win.attributes("-topmost", True)
        self.tip_win.configure(bg=TIP_BG_COLOR)
        self.tip_label = tk.Label(
            self.tip_win, text="", bg=TIP_BG_COLOR, fg=TIP_FG_COLOR,
            font=("Consolas", 8), justify=tk.LEFT
        )
        self.tip_label.pack(ipadx=6, ipady=3)
        self.draw_cross_line(event.x, event.y)

    def on_chart_mouse_move(self, event):
        """鼠标在图表内移动，实时更新十字线+提示信息"""
        if self.tip_win is None:
            return
        self.mouse_x = event.x
        self.mouse_y = event.y
        x, y = event.x, event.y
        pad, bottom, right, top = self._inner_rect

        # 实时刷新十字线
        self.draw_cross_line(x, y)

        # 匹配最近时间点数据
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

        # 组装提示文字
        _, hhmm, break_rate, fall_rate = near_data
        text = f"时间：{hhmm}\n昨量价突破：{break_rate:.2f}%\n昨冲高回落：{fall_rate:.2f}%"
        self.tip_label.config(text=text)

        # 智能避让屏幕边缘
        win_x = self.chart_canvas.winfo_rootx() + x + 15
        win_y = self.chart_canvas.winfo_rooty() + y + 15
        w, h = 120, 50
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if win_x + w > sw:
            win_x = self.chart_canvas.winfo_rootx() + x - w - 15
        if win_y + h > sh:
            win_y = self.chart_canvas.winfo_rooty() + y - h - 15
        self.tip_win.geometry(f"{w}x{h}+{win_x}+{win_y}")

    def on_chart_leave(self, event):
        """鼠标离开图表区域，销毁提示窗+清除十字线"""
        self.mouse_in_chart = False
        if self.tip_win is not None:
            self.tip_win.destroy()
            self.tip_win = None
            self.tip_label = None
        self.chart_canvas.delete(self.cross_tag)

    def on_chart_resize(self, event):
        """窗口大小改变，重绘图表"""
        self.draw_chart()

    def start_chart_refresh_loop(self):
        """后台线程定时刷新走势图"""
        def loop():
            while self.running_flag:
                time.sleep(CHART_REFRESH_INTERVAL)
                self.root.after_idle(self.draw_chart)
        threading.Thread(target=loop, daemon=True).start()

    # ====================== 日志窗口功能 ======================
    def limit_log_lines(self, text_widget):
        """限制日志文本框最大行数，超出自动清空顶部"""
        cnt = int(text_widget.index(tk.END).split('.')[0])
        if cnt > MAX_LOG_LINES:
            text_widget.delete("1.0", f"{cnt-MAX_LOG_LINES}.0")

    def bind_scroll_event(self):
        """绑定鼠标滚轮事件，标记手动浏览状态"""
        boxes = [self.t1, self.t2, self.t3, self.t4, self.t5]
        def cb(e):
            self.manual_view = True
            self.last_scroll_time = time.time()
        for b in boxes:
            b.bind("<MouseWheel>", cb)

    def safe_append_log(self, wd, msg):
        """线程安全添加日志信息"""
        def inner():
            t = time.strftime("%H:%M:%S")
            wd.insert(tk.END, f"[{t}] {msg}\n")
            self.limit_log_lines(wd)
            # 静置超时恢复自动滚动
            if self.manual_view and time.time()-self.last_scroll_time > RESUME_FOLLOW_DELAY:
                self.manual_view = False
            if not self.manual_view:
                wd.see(tk.END)
        self.root.after_idle(inner)

    def bind_drag_event(self):
        """拖拽分割栏时临时禁用日志编辑"""
        def start(_):
            for w in [self.t1, self.t2, self.t3, self.t4, self.t5]:
                w.config(state=tk.DISABLED)
        def end(_):
            for w in [self.t1, self.t2, self.t3, self.t4, self.t5]:
                w.config(state=tk.NORMAL)
        for p in [self.top_pane, self.mid_pane, self.main_pane]:
            p.bind("<ButtonPress-1>", start)
            p.bind("<ButtonRelease-1>", end)

    # 快捷日志输出方法
    def log_warn(self, msg):self.safe_append_log(self.t1, msg)
    def log_strong(self, msg):self.safe_append_log(self.t2, msg)
    def log_market(self, msg):self.safe_append_log(self.t3, msg)
    def log_position(self, msg):self.safe_append_log(self.t4, msg)
    def log_system(self, msg):self.safe_append_log(self.t5, msg)

    def get_text_widget(self, k):
        """根据key获取对应日志文本框"""
        m = {"t1":self.t1,"t2":self.t2,"t3":self.t3,"t4":self.t4,"t5":self.t5}
        return m.get(k)

    def single_file_monitor(self, key, path):
        """单文件日志监听线程：增量读取日志"""
        pos = self.file_read_pos[key]
        wd = self.get_text_widget(key)
        while self.running_flag:
            try:
                if not os.path.exists(path):
                    time.sleep(LOG_POLL_INTERVAL)
                    continue
                # 从上次读取位置继续读取
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    lines = f.readlines()
                    pos = f.tell()
                    self.file_read_pos[key] = pos
                if lines:
                    cont = "".join(lines)
                    # 昨日筛选日志同步解析为图表数据
                    if key == "t3":
                        arr = self.parse_log_chart_data(cont)
                        self.update_chart_cache(arr)
                    # UI更新放入主线程
                    def ui_up():
                        wd.insert(tk.END, cont)
                        self.limit_log_lines(wd)
                        if self.manual_view and time.time()-self.last_scroll_time > RESUME_FOLLOW_DELAY:
                            self.manual_view = False
                        if not self.manual_view:
                            wd.see(tk.END)
                    self.root.after_idle(ui_up)
            except Exception:
                pass
            time.sleep(LOG_POLL_INTERVAL)

    def start_file_monitor_threads(self):
        """批量启动所有日志监听线程"""
        for k, p in LOG_FILE_MAP.items():
            threading.Thread(target=self.single_file_monitor, args=(k, p), daemon=True).start()

    def close_all_monitor(self):
        """关闭程序时终止所有线程与窗口"""
        self.running_flag = False
        if self.tip_win:
            self.tip_win.destroy()
        self.chart_canvas.delete(self.cross_tag)

# ====================== 模拟测试数据生成函数 ======================
def mock_market_data_writer():
    """生成仿真行情日志，用于本地测试无需对接实盘"""
    log_path = LOG_FILE_MAP["t3"]
    # 清空旧日志
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("")

    cur_min = MORNING_START
    import random

    while True:
        if not app.running_flag:
            break
        # 跳过午休时段
        if MORNING_END < cur_min < AFTER_START:
            cur_min = AFTER_START
        # 收盘后重置从头开始
        if cur_min > AFTER_END:
            cur_min = MORNING_START
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("")

        hh = cur_min // 60
        mm = cur_min % 60
        hhmm_str = f"{hh:02d}:{mm:02d}"
        date_str = "2026-06-30"

        # 随机生成两组平均涨跌幅
        val_break = round(random.uniform(-2.5, 6.5), 2)
        val_drop = round(random.uniform(-5.5, 3.0), 2)

        # 拼接和真实格式一致的日志内容
        log_text = f"""—————————— {date_str} {hhmm_str} 昨筛选强度监控 ——————————
【昨量价突破组】共6只 | 平均涨幅：{val_break}%
机器人　  8.12% | 聚和材料  3.04% | 荣昌生物  2.14%
金宏气体  6.10% | 广钢气体  2.45% | 贝达药业 -0.37%
【昨冲高回落组】共43只 | 平均涨幅：{val_drop}%
晶瑞电材  5.72% | 宏景科技  0.34% | 铂科新材 -1.16% | 东方钽业 -2.51%
昊华科技  4.70% | 澜起科技  0.20% | 江钨装备 -1.31% | 飞凯材料 -2.80%

"""
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_text)

        cur_min += 1
        time.sleep(0.6)

# ====================== 程序入口 ======================
if __name__ == "__main__":
    root = tk.Tk()
    app = QuantLogPanel(root)

    # 关闭窗口回调
    def on_close():
        app.close_all_monitor()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    # 开启模拟数据测试(注释则关闭)
    # threading.Thread(target=mock_market_data_writer, daemon=True).start()

    # 启动主循环
    root.mainloop()