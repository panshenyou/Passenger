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
LOG_FONT_SIZE = 7                  # 日志内容字体大小
TITLE_FONT_SIZE = 10               # 分区标题字体大小
LOG_POLL_INTERVAL = 0.2            # 日志文件读取轮询间隔(秒)
CHART_REFRESH_INTERVAL = 0.3       # 分时图表后台刷新间隔(秒)
CHART_PADDING = 25                 # 缩小图表内边距
LINE_WIDTH = 1.0                   # 线条粗细适配盘口
ABNORMAL_LOG_MIN_HEIGHT = 140       # 异常原因日志最小高度

# 专业看盘软件悬浮提示窗配色（商务深灰）
TIP_BG_COLOR = "#242A35"
TIP_FG_COLOR = "#E8EDF2"
TIP_BORDER_COLOR = "#505A6B"

# 分时图十字准星虚线样式
CROSS_LINE_COLOR = "#6B788C"
CROSS_DASH_STYLE = (5, 3)

# A股交易时间 换算为分钟数
MORNING_START = 570    # 09:30
MORNING_END = 690      # 11:30
AFTER_START = 780      # 13:00
AFTER_END = 900        # 15:00

# ====================== 日志文件路径配置 ======================
QMT_PROJECT_ROOT = r"C:\Users\15113\Desktop\QMT_Software\py_strategy"
SCRIPT_DIR = os.path.join(QMT_PROJECT_ROOT, "log")
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

# ====================== 主界面监控面板类【专业看盘商务深灰配色】 ======================
class QuantLogPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("量化监控终端")
        self.root.geometry("1280x768")
        self.root.resizable(True, True)

        # ========== 【全新专业看盘级配色体系 - 通达信商务深灰风】 ==========
        MAIN_BG = "#1A202C"          # 主窗口底色 高级深灰
        PANEL_BG = "#232B38"         # 面板容器底色
        TEXT_NORMAL = "#CBD5E1"      # 常规日志浅灰文字
        TEXT_TITLE = "#F1F5F9"       # 分区标题高亮白字
        CURSOR_COLOR = "#94A3B8"     # 光标柔和灰
        CHART_BG = "#1E2633"         # 分时图表专用底色
        LINE_GRAY = "#94A3B8"        # 量价突破中性灰线
        LINE_WHITE = "#E2E8F0"       # 冲高回落主走势亮白线
        LINE_TOP20 = "#FBBF24"       # Top20统计黄金色
        AXIS_COLOR = "#475569"       # 坐标轴暗灰
        TEXT_CHART_COLOR = "#94A3B8" # 图表刻度文字
        RISE_RED = "#EF4444"         # 行情标准上涨红
        FALL_GREEN = "#10B981"       # 行情标准下跌绿
        GRID_LINE = "#334155"        # 图表网格浅暗线

        # 绑定全局配色
        self.MAIN_BG = MAIN_BG
        self.PANEL_BG = PANEL_BG
        self.TEXT_NORMAL = TEXT_NORMAL
        self.TEXT_TITLE = TEXT_TITLE
        self.CHART_BG = CHART_BG
        self.LINE_GRAY = LINE_GRAY
        self.LINE_WHITE = LINE_WHITE
        self.LINE_TOP20 = LINE_TOP20
        self.AXIS_COLOR = AXIS_COLOR
        self.TEXT_CHART_COLOR = TEXT_CHART_COLOR
        self.RISE_RED = RISE_RED
        self.FALL_GREEN = FALL_GREEN
        self.GRID_LINE = GRID_LINE

        # 日志滚动状态标记
        self.manual_view = False
        self.last_scroll_time = 0
        self.file_read_pos = {k: 0 for k in LOG_FILE_MAP.keys()}
        self.running_flag = True

        # 分时图数据缓存
        self.chart_data = []
        self.tip_win = None
        self.tip_label = None
        self.cross_tag = "cross_line"
        self.mouse_in_chart = False
        self.mouse_x = 0
        self.mouse_y = 0
        self._chart_x_map = []
        self._get_x_pos_func = None
        self._get_y_range = (0, 0)
        self._inner_rect = (0, 0, 0, 0)

        # 主窗口底色
        self.root.configure(bg=MAIN_BG)

        # ========== 全局样式美化（专业终端质感） ==========
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TPanedWindow", background=MAIN_BG, borderwidth=1)
        # 分割条高级暗色调
        style.configure("VSash", background="#334155")
        style.configure("HSash", background="#334155")
        # 专业极简滚动条
        style.configure("TScrollbar",
                        background=PANEL_BG,
                        troughcolor=MAIN_BG,
                        borderwidth=0,
                        relief=tk.FLAT,
                        arrowcolor=TEXT_NORMAL)
        style.map("TScrollbar", background=[("active", "#475569"), ("pressed", "#64748B")])

        # ====================== 整体布局搭建（窄边距最大化日志区） ======================
        self.main_pane = ttk.PanedWindow(root, orient=tk.VERTICAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # 上层左右双日志窗口
        self.top_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.top_pane, weight=2)

        # 左侧：异动涨跌区
        f1 = tk.Frame(self.top_pane, bg=PANEL_BG, bd=0)
        self.top_pane.add(f1, weight=1)
        tk.Label(f1, text="异动涨跌监控区", fg=self.TEXT_TITLE, bg=PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t1 = tk.Text(f1, font=("微软雅黑", LOG_FONT_SIZE), bg=MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s1 = ttk.Scrollbar(f1, command=self.t1.yview)
        s1.pack(side=tk.RIGHT, fill=tk.Y)
        self.t1.config(yscrollcommand=s1.set)

        # 右侧：冲高回落区
        f2 = tk.Frame(self.top_pane, bg=PANEL_BG, bd=0)
        self.top_pane.add(f2, weight=1)
        tk.Label(f2, text="冲高回落预警区", fg=self.TEXT_TITLE, bg=PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t2 = tk.Text(f2, font=("微软雅黑", LOG_FONT_SIZE), bg=MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s2 = ttk.Scrollbar(f2, command=self.t2.yview)
        s2.pack(side=tk.RIGHT, fill=tk.Y)
        self.t2.config(yscrollcommand=s2.set)

        # 中层左右双日志窗口
        self.mid_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.mid_pane, weight=2)

        # 左侧：昨日筛选区
        f3 = tk.Frame(self.mid_pane, bg=PANEL_BG, bd=0)
        self.mid_pane.add(f3, weight=1)
        tk.Label(f3, text="昨日强度筛选池", fg=self.TEXT_TITLE, bg=PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t3 = tk.Text(f3, font=("微软雅黑", LOG_FONT_SIZE), bg=MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t3.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s3 = ttk.Scrollbar(f3, command=self.t3.yview)
        s3.pack(side=tk.RIGHT, fill=tk.Y)
        self.t3.config(yscrollcommand=s3.set)

        # 右侧：量价齐升区
        f4 = tk.Frame(self.mid_pane, bg=PANEL_BG, bd=0)
        self.mid_pane.add(f4, weight=1)
        tk.Label(f4, text="量价齐升突破区", fg=self.TEXT_TITLE, bg=PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t4 = tk.Text(f4, font=("微软雅黑", LOG_FONT_SIZE), bg=MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t4.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s4 = ttk.Scrollbar(f4, command=self.t4.yview)
        s4.pack(side=tk.RIGHT, fill=tk.Y)
        self.t4.config(yscrollcommand=s4.set)

        # 下层：左侧日志 + 右侧分时图
        bottom_main = tk.Frame(self.main_pane, bg=MAIN_BG)
        self.main_pane.add(bottom_main, weight=2)
        bottom_pane = ttk.PanedWindow(bottom_main, orient=tk.HORIZONTAL)
        bottom_pane.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 左侧：强势监控日志
        left_log_frame = tk.Frame(bottom_pane, bg=PANEL_BG, bd=0)
        bottom_pane.add(left_log_frame, weight=11)
        tk.Label(left_log_frame, text="市场强势股监控", fg=self.TEXT_TITLE, bg=PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t5 = tk.Text(left_log_frame, font=("微软雅黑", LOG_FONT_SIZE), bg=MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t5.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s5 = ttk.Scrollbar(left_log_frame, command=self.t5.yview)
        s5.pack(side=tk.RIGHT, fill=tk.Y)
        self.t5.config(yscrollcommand=s5.set)

        # 右侧：专业分时图画布
        chart_frame = tk.Frame(bottom_pane, bg=PANEL_BG, bd=0)
        bottom_pane.add(chart_frame, weight=15)
        tk.Label(chart_frame, text="市场强度分时图(白=冲高回落 灰=量价突破 黄=成交Top20平均回撤)",
                 fg=self.TEXT_TITLE, bg=PANEL_BG, font=("微软雅黑", TITLE_FONT_SIZE-1, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.chart_canvas = tk.Canvas(chart_frame, bg=self.CHART_BG, bd=0, highlightthickness=0)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.chart_canvas.bind("<Configure>", self.on_chart_resize)

        # 最底部：异动原因特殊监控区
        abnormal_frame = tk.Frame(self.main_pane, bg=PANEL_BG, height=ABNORMAL_LOG_MIN_HEIGHT, bd=0)
        self.main_pane.add(abnormal_frame, weight=0)
        abnormal_frame.pack_propagate(False)

        tk.Label(abnormal_frame, text="AI异动逻辑解析(通义千问)", fg=self.TEXT_TITLE, bg=PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t6 = tk.Text(abnormal_frame, font=("微软雅黑", LOG_FONT_SIZE), bg="#171E2B", fg=self.TEXT_NORMAL,
                          insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t6.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
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

    # ====================== 工具方法（完全无修改） ======================
    def time_to_minute(self, time_str):
        h, m = map(int, time_str.split(":"))
        return h * 60 + m

    def parse_log_chart_data(self, log_content):
        res = []
        lines = log_content.splitlines()
        temp_dict = {}

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
            t_match = time_reg.search(line)
            if t_match:
                if curr_time and brk_val is not None and fall_val is not None and top_val is not None:
                    temp_dict[curr_time] = (brk_val, fall_val, top_val)
                curr_time = t_match.group(1)
                brk_val = fall_val = top_val = None

            bm = break_reg.search(line)
            if bm:
                brk_val = float(bm.group(1))
            fm = fall_reg.search(line)
            if fm:
                fall_val = float(fm.group(1))
            tm = top20_reg.search(line)
            if tm:
                top_val = float(tm.group(1))

        if curr_time and brk_val is not None and fall_val is not None and top_val is not None:
            temp_dict[curr_time] = (brk_val, fall_val, top_val)

        for tm_str, (b, f, t) in temp_dict.items():
            minute = self.time_to_minute(tm_str)
            if MORNING_START <= minute <= AFTER_END:
                res.append((minute, tm_str, b, f, t))

        res.sort(key=lambda x: x[0])
        return res

    def update_chart_cache(self, new_data_list):
        if not new_data_list:
            return
        exist_keys = set((d[0], d[1]) for d in self.chart_data)
        for item in new_data_list:
            if (item[0], item[1]) not in exist_keys:
                self.chart_data.append(item)
        self.chart_data.sort(key=lambda x: x[0])

    # ====================== 分时图绘制（仅色调变更，绘制逻辑完全不变） ======================
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
            canvas.create_text(px, ch-pad+14, text=txt, fill=self.TEXT_CHART_COLOR, font=("微软雅黑",8), tag="chart_item")

        # Y轴网格线
        y_step = (max_y - min_y) / 5
        for i in range(6):
            yv = min_y + y_step * i
            yp = v2y(yv)
            canvas.create_line(pad, yp, cw-pad, yp, fill=self.GRID_LINE, width=1, tag="chart_item")
            canvas.create_text(pad-8, yp, text=f"{yv:.1f}", fill=self.TEXT_CHART_COLOR, font=("微软雅黑",8), anchor=tk.E, tag="chart_item")

        # 零轴醒目虚线
        zero_y = v2y(0)
        if pad < zero_y < ch-pad:
            canvas.create_line(pad, zero_y, cw-pad, zero_y, fill="#64748B", width=1.2, dash=(2,2), tag="chart_item")

        # 三条曲线绘制逻辑完全不变
        if len(self.chart_data) >= 2:
            # 灰线：量价突破
            pts = [(time_to_valid_x(d[0]), v2y(d[2])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_GRAY, width=LINE_WIDTH, tag="chart_item")
            # 白线：冲高回落(主走势线)
            pts = [(time_to_valid_x(d[0]), v2y(d[3])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_WHITE, width=LINE_WIDTH+0.2, tag="chart_item")
            # 黄金线：Top20均价回撤
            pts = [(time_to_valid_x(d[0]), v2y(d[4])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_TOP20, width=LINE_WIDTH, tag="chart_item")

        self._chart_x_map = [(time_to_valid_x(d[0]), d) for d in self.chart_data]
        self._get_x_pos_func = time_to_valid_x
        self._get_y_range = (min_y, max_y)
        self._inner_rect = (pad, ch-pad, cw-pad, pad)

        # Top20资金出逃风险标记
        first_risk_pos = None
        for data in self.chart_data:
            top20_dd = data[4]
            if top20_dd < -3.0:
                first_risk_pos = data
                break
        if first_risk_pos:
            risk_x = time_to_valid_x(first_risk_pos[0])
            risk_y = v2y(first_risk_pos[4])
            canvas.create_oval(risk_x-3, risk_y-3, risk_x+3, risk_y+3, fill=self.FALL_GREEN, outline=self.FALL_GREEN, tag="chart_item")
            tip_x = 150
            tip_y = ch - 30
            warn_text = f"资金出逃嫌疑，切新题材或打首板"
            txt_w = len(warn_text) * 12
            txt_h = 12
            canvas.create_rectangle(tip_x-txt_w/2-4, tip_y-txt_h/2-2, tip_x+txt_w/2+4, tip_y+txt_h/2+2,
                                     fill="", outline=self.FALL_GREEN, width=1, dash=(3,3), tag="chart_item")
            canvas.create_text(tip_x, tip_y, text=warn_text, fill=self.FALL_GREEN, font=("微软雅黑",8,"bold"), anchor=tk.CENTER, tag="chart_item")
            canvas.create_line(tip_x, tip_y-txt_h/2-2, risk_x, risk_y+3, fill=self.FALL_GREEN, width=1.2, dash=(3,3), arrow=tk.FIRST, tag="chart_item")

        # 量价突破强弱标记
        first_risk_pos = None
        VolPriceBreak_up_or_down = 0
        VolPriceBreak_Color = None
        for data in self.chart_data:
            top20_dd = data[2]
            if top20_dd > 2.0:
                first_risk_pos = data
                VolPriceBreak_up_or_down = 1
                VolPriceBreak_Color = self.RISE_RED
                break
            elif top20_dd < -2.0:
                first_risk_pos = data
                VolPriceBreak_up_or_down = 2
                VolPriceBreak_Color = self.FALL_GREEN
                break
        if first_risk_pos:
            risk_x = time_to_valid_x(first_risk_pos[0])
            risk_y = v2y(first_risk_pos[2])
            canvas.create_oval(risk_x-3, risk_y-3, risk_x+3, risk_y+3, fill=VolPriceBreak_Color, outline=VolPriceBreak_Color, tag="chart_item")
            # 动态居中中上位置，随窗口自适应
            tip_x = pad + inner_w * 0.4
            tip_y = pad + inner_h * 0.1
            warn_text = "昨量价齐升，持续性强，可追高" if VolPriceBreak_up_or_down==1 else f"昨量价齐升，持续性差，别追高"
            txt_len = len(warn_text) * 12
            canvas.create_rectangle(tip_x - txt_len/2 - 4, tip_y - 8, tip_x + txt_len/2 + 4, tip_y + 8,
                             fill="", outline=VolPriceBreak_Color, width=1, dash=(3,3), tag="chart_item")
            canvas.create_text(tip_x, tip_y, text=warn_text, fill=VolPriceBreak_Color, font=("微软雅黑",8,"bold"), anchor=tk.CENTER, tag="chart_item")
            canvas.create_line(tip_x, tip_y + 10, risk_x, risk_y + 3, fill=VolPriceBreak_Color, width=1.2, dash=(3,3), arrow=tk.FIRST, tag="chart_item")


        # 冲高回落情绪标记
        first_risk_pos = None
        CommonDrawdown_up_or_down = None
        CommonDrawdown_Color = None
        for data in self.chart_data:
            top20_dd = data[3]
            if top20_dd > 2.0:
                first_risk_pos = data
                CommonDrawdown_up_or_down = 1
                CommonDrawdown_Color = self.RISE_RED
                break
            elif top20_dd < -2.0:
                first_risk_pos = data
                CommonDrawdown_up_or_down = 2
                CommonDrawdown_Color = self.FALL_GREEN
                break
        if first_risk_pos:
            risk_x = time_to_valid_x(first_risk_pos[0])
            risk_y = v2y(first_risk_pos[3])
            canvas.create_oval(risk_x-3, risk_y-3, risk_x+3, risk_y+3, fill=CommonDrawdown_Color, outline=CommonDrawdown_Color, tag="chart_item")
            tip_x = 420
            tip_y = ch - 32
            warn_text = f"超预期，做多意愿强，可考虑今冲高回落" if CommonDrawdown_up_or_down==1 else f"资金割肉，恐慌情绪蔓延，小心冲高回落"
            txt_w = len(warn_text) * 12
            canvas.create_rectangle(tip_x-txt_w/2-4, tip_y-8, tip_x+txt_w/2+4, tip_y+8, fill="", outline=CommonDrawdown_Color, width=1, dash=(3,3), tag="chart_item")
            canvas.create_text(tip_x, tip_y, text=warn_text, fill=CommonDrawdown_Color, font=("微软雅黑",8,"bold"), anchor=tk.CENTER, tag="chart_item")
            canvas.create_line(tip_x, tip_y-10, risk_x, risk_y+3, fill=CommonDrawdown_Color, width=1.2, dash=(3,3), arrow=tk.FIRST, tag="chart_item")

        if self.mouse_in_chart:
            self.draw_cross_line(self.mouse_x, self.mouse_y)

    def draw_cross_line(self, x, y):
        pad, bottom, right, top = self._inner_rect
        self.chart_canvas.delete(self.cross_tag)
        if pad < x < right and top < y < bottom:
            self.chart_canvas.create_line(x, top, x, bottom, fill=CROSS_LINE_COLOR,dash=CROSS_DASH_STYLE, width=1, tag=self.cross_tag)
            self.chart_canvas.create_line(pad, y, right, y, fill=CROSS_LINE_COLOR,dash=CROSS_DASH_STYLE, width=1, tag=self.cross_tag)

    # ====================== 鼠标事件（无任何修改） ======================
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
        self.tip_label = tk.Label(self.tip_win, text="", bg=TIP_BG_COLOR, fg=TIP_FG_COLOR,
                                  font=("微软雅黑", 8), justify=tk.LEFT)
        self.tip_label.pack(ipadx=8, ipady=4)
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
        text = (f"交易时间：{hhmm}\n"
                f"量价突破强度：{break_rate:.2f}%\n"
                f"冲高回落幅度：{fall_rate:.2f}%\n"
                f"Top20平均回撤：{top20_dd:.2f}%")
        self.tip_label.config(text=text)

        win_x = self.chart_canvas.winfo_rootx() + x + 18
        win_y = self.chart_canvas.winfo_rooty() + y + 18
        w, h = 155, 70
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if win_x + w > sw:
            win_x = self.chart_canvas.winfo_rootx() + x - w - 18
        if win_y + h > sh:
            win_y = self.chart_canvas.winfo_rooty() + y - h - 18
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

    # ====================== 日志窗口全部原生逻辑不动 ======================
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
                    if key == "t3":
                        arr = self.parse_log_chart_data(cont)
                        self.update_chart_cache(arr)
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
        print("\n[INFO] 程序正常退出")
        on_close()