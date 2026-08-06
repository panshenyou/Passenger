import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import time
import threading
import os
import sys
import re
import json
from PIL import Image, ImageTk

# ====================== 全局配置参数 ======================
MAX_LOG_LINES = 60                 # 每个日志区域最大显示行数
RESUME_FOLLOW_DELAY = 3.0          # 手动滑动日志后，静置多久恢复自动滚动
LOG_FONT_SIZE = 7                  # 日志内容字体大小
TITLE_FONT_SIZE = 8               # 分区标题字体大小
LOG_POLL_INTERVAL = 0.2            # 日志文件读取轮询间隔(秒)
CHART_REFRESH_INTERVAL = 0.3       # 分时图表后台刷新间隔(秒)
CHART_PADDING = 25                 # 缩小图表内边距
LINE_WIDTH = 1.0                   # 线条粗细适配盘口
ABNORMAL_LOG_MIN_HEIGHT = 140       # 异常原因日志最小高度

# ====================== 日志文件路径配置 ======================
QMT_PROJECT_ROOT = r"C:\Users\15113\Desktop\QMT_Software\py_strategy"
# 图片总目录
IMG_STORE_DIR = os.path.join(QMT_PROJECT_ROOT, "note_images")
IMG_SUB_DIR_1 = "note1"
IMG_SUB_DIR_2 = "note2"
# 笔记JSON文件放入note_images目录下
NOTE_SAVE_PATH_1 = os.path.join(IMG_STORE_DIR, "replay_note1.json")
NOTE_SAVE_PATH_2 = os.path.join(IMG_STORE_DIR, "replay_note2.json")

SCRIPT_DIR = os.path.join(QMT_PROJECT_ROOT, "log")
LOG_FILE_NAME_MAP = {
    "t1": "Log_PositionStock.txt",          # t1窗口：异动涨跌区日志
    "t2": "Log_CommonDrawdown.txt",        # t2窗口：冲高回落区日志
    "t3": "Log_StockStrengthYesterday.txt", # t3窗口：昨日筛选区(分时图数据源)
    "t4": "Log_VolPriceBreak.txt",          # t4窗口：量价齐升区日志
    "t5": "Log_StrongStock.txt",            # t5窗口：强势监控区日志
    "t6": "Log_AbnormalReason.txt",          # t6窗口：异动原因特殊监控区
    "t7": "Log_SmallArbitrageStock.txt"      # t7窗口：小盘套利监控区
}
# 拼接为绝对路径
LOG_FILE_MAP = {k: os.path.join(SCRIPT_DIR, v) for k, v in LOG_FILE_NAME_MAP.items()}

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

# ====================== 主界面监控面板类【专业看盘商务深灰配色】 ======================
class QuantLogPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("QMT策略监控面板")
        self.root.geometry("1280x768")
        self.root.resizable(True, True)
        # 初始化图片文件夹（位于QMT_PROJECT_ROOT下）
        self.init_img_dir()

        # ========== 【全新专业看盘级配色体系 - 通达信商务深灰风】 ==========
        MAIN_BG = "#1A202C"          # 主窗口底色 高级深灰
        PANEL_BG = "#232B38"         # 面板容器底色
        TEXT_NORMAL = "#CBD5E1"      # 常规日志浅灰文字
        TEXT_TITLE = "#F1F5F9"       # 分区标题高亮白字
        CURSOR_COLOR = "#94A3B8"     # 光标柔和灰
        CHART_BG = "#1E2633"         # 分时图表专用底色

        #配色方案1
        #LINE_PRICEBREAK = "#5E81AC"  # 量价突破中性蓝线
        #LINE_UPDOWN = "#ECEFF4"       # 冲高回落主走势亮白线
        #LINE_TOP20 = "#D08770"       # Top20统计黄金色
        #LINE_ARBITRAGE = "#B48EAD"   # 小盘套利粉色曲线
        #配色方案2
        #LINE_PRICEBREAK = "#0072B2"  # 量价突破中性蓝线
        #LINE_UPDOWN = "#E69F00"       # 冲高回落主走势亮白线
        #LINE_TOP20 = "#009E73"       # Top20统计黄金色
        #LINE_ARBITRAGE = "#CC79A7"   # 小盘套利粉色曲线
        #配色方案3
        LINE_PRICEBREAK = "#0088FF"  # 量价突破中性蓝线
        LINE_UPDOWN = "#10B981"       # 冲高回落主走势亮白线
        LINE_TOP20 = "#FFBB00"       # Top20统计黄金色
        LINE_ARBITRAGE = "#FFFFFF"   # 小盘套利粉色曲线

        AXIS_COLOR = "#475569"       # 坐标轴暗灰
        TEXT_CHART_COLOR = "#94A3B8" # 图表刻度文字
        RISE_RED = "#EF4444"         # 行情标准上涨红
        FALL_GREEN = "#10B981"       # 行情标准下跌绿
        GRID_LINE = "#334155"        # 图表网格浅暗线
        NOTE_BG = "#171E2B"          # 笔记编辑区底色
        # 全部配色提前绑定self
        self.MAIN_BG = MAIN_BG
        self.PANEL_BG = PANEL_BG
        self.TEXT_NORMAL = TEXT_NORMAL
        self.TEXT_TITLE = TEXT_TITLE
        self.CURSOR_COLOR = CURSOR_COLOR
        self.CHART_BG = CHART_BG
        self.LINE_PRICEBREAK = LINE_PRICEBREAK
        self.LINE_UPDOWN = LINE_UPDOWN
        self.LINE_TOP20 = LINE_TOP20
        self.LINE_ARBITRAGE = LINE_ARBITRAGE
        self.AXIS_COLOR = AXIS_COLOR
        self.TEXT_CHART_COLOR = TEXT_CHART_COLOR
        self.RISE_RED = RISE_RED
        self.FALL_GREEN = FALL_GREEN
        self.GRID_LINE = GRID_LINE
        self.NOTE_BG = NOTE_BG
        # 日志滚动状态标记
        self.manual_view = False
        self.last_scroll_time = 0
        self.file_read_pos = {k: 0 for k in LOG_FILE_MAP.keys()}
        self.running_flag = True
        # 分时图数据缓存 (元组：minute, tm_str, break, fall, top20, arbitrage)
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
        # ========== 两套复盘笔记独立变量 ==========
        # 笔记1
        self.note1_images = {}       # key:图片名称, value:ImageTk对象
        self.note1_img_idx = 0
        self.note1_modified = False
        # 笔记2
        self.note2_images = {}
        self.note2_img_idx = 0
        self.note2_modified = False

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
        # 按钮深色样式
        style.configure("Note.TButton", background="#334155", foreground=TEXT_TITLE)
        style.map("Note.TButton", background=[("active", "#475569")])
        # ====================== 顶层Tab标签容器 ======================
        self.tab_root = ttk.Notebook(self.root)
        self.tab_root.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        # Tab1：原有监控面板
        self.tab_monitor = tk.Frame(self.tab_root, bg=MAIN_BG)
        self.tab_root.add(self.tab_monitor, text="策略监控面板")
        # Tab2：交易复盘笔记
        self.tab_note1 = tk.Frame(self.tab_root, bg=MAIN_BG)
        self.tab_root.add(self.tab_note1, text="复盘笔记")
        # Tab3：情绪周期
        self.tab_note2 = tk.Frame(self.tab_root, bg=MAIN_BG)
        self.tab_root.add(self.tab_note2, text="情绪周期")
        # 构建界面
        self.build_monitor_layout()
        self.build_note_layout_1()
        self.build_note_layout_2()
        # 绑定事件、启动线程
        self.bind_scroll_event()
        self.bind_drag_event()
        self.start_file_monitor_threads()
        self.start_chart_refresh_loop()
        self.chart_canvas.bind("<Enter>", self.on_chart_enter)
        self.chart_canvas.bind("<Motion>", self.on_chart_mouse_move)
        self.chart_canvas.bind("<Leave>", self.on_chart_leave)
        self.root.after(200, self.draw_chart)
        # 启动加载两份笔记
        self.load_replay_note1()
        self.load_replay_note2()
        # 切换Tab自动保存当前激活笔记
        self.tab_root.bind("<<NotebookTabChanged>>", self.on_tab_switch)

    # ====================== 图片文件夹初始化工具 ======================
    def init_img_dir(self):
        """创建根图片目录+两个子目录（全部在QMT_PROJECT_ROOT下）"""
        self.dir_note1 = os.path.join(IMG_STORE_DIR, IMG_SUB_DIR_1)
        self.dir_note2 = os.path.join(IMG_STORE_DIR, IMG_SUB_DIR_2)
        for d in [IMG_STORE_DIR, self.dir_note1, self.dir_note2]:
            if not os.path.exists(d):
                os.makedirs(d)

    def get_note1_img_path(self, filename):
        return os.path.join(self.dir_note1, filename)

    def get_note2_img_path(self, filename):
        return os.path.join(self.dir_note2, filename)

    # ====================== Tab切换自动保存当前激活笔记 ======================
    def on_tab_switch(self, event):
        idx = self.tab_root.index(self.tab_root.select())
        # 0=监控面板，1=笔记1，2=笔记2
        if idx == 1 and self.note1_modified:
            self.save_replay_note1()
        elif idx == 2 and self.note2_modified:
            self.save_replay_note2()

    def parse_t3_group_lines(self, lines):
        """
        解析t3多行日志，返回 [(行文本, tag名)]
        实现：分组标题 + 组内股票全部同色
        """
        import re
        # 分组标题正则，捕获组别标识
        reg_group_break = re.compile(r"量价突破")
        reg_group_fall = re.compile(r"冲高回落")
        reg_group_top20 = re.compile(r"Top20")
        reg_group_arb = re.compile(r"小市值套利")
        # 股票行特征：包含数字百分号 %，无新分组标识
        reg_stock_line = re.compile(r"\d+\.?\d+%")

        current_tag = None
        line_tag_list = []

        for line in lines:
            line_strip = line.strip()
            if not line_strip:
                line_tag_list.append((line, None))
                continue
        
            # 匹配分组标题，切换当前tag
            if reg_group_break.search(line):
                current_tag = "tag_break"
                line_tag_list.append((line, current_tag))
            elif reg_group_fall.search(line):
                current_tag = "tag_fall"
                line_tag_list.append((line, current_tag))
            elif reg_group_top20.search(line):
                current_tag = "tag_top20"
                line_tag_list.append((line, current_tag))
            elif reg_group_arb.search(line):
                current_tag = "tag_arbitrage"
                line_tag_list.append((line, current_tag))
            else:
                # 普通行：如果当前有分组，且是股票明细则沿用分组颜色
                if current_tag is not None and reg_stock_line.search(line):
                    line_tag_list.append((line, current_tag))
                else:
                    line_tag_list.append((line, None))
        return line_tag_list
    # ====================== 【修改后的监控界面布局】 ======================
    # 布局规则：
    # 上层：t1 异动涨跌 | t5 市场强势股
    # 中层：t3 昨日强度 | 分时图表（新增实时数值状态栏）
    # 下层：t2 冲高回落 | t4 量价齐升
    # 底部：t6 异动解析 | t7 小盘套利
    def build_monitor_layout(self):
        self.main_pane = ttk.PanedWindow(self.tab_monitor, orient=tk.VERTICAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        # ========== 上层：t1 异动涨跌 | t5 市场强势股 ==========
        self.top_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.top_pane, weight=2)
        # t1
        f1 = tk.Frame(self.top_pane, bg=self.PANEL_BG, bd=0)
        self.top_pane.add(f1, weight=1)
        tk.Label(f1, text="异动涨跌监控区", fg=self.TEXT_TITLE, bg=self.PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t1 = tk.Text(f1, font=("微软雅黑", LOG_FONT_SIZE), bg=self.MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=self.CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s1 = ttk.Scrollbar(f1, command=self.t1.yview)
        s1.pack(side=tk.RIGHT, fill=tk.Y)
        self.t1.config(yscrollcommand=s1.set)

        # t5
        f5 = tk.Frame(self.top_pane, bg=self.PANEL_BG, bd=0)
        self.top_pane.add(f5, weight=1)
        tk.Label(f5, text="市场强势股监控", fg=self.TEXT_TITLE, bg=self.PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t5 = tk.Text(f5, font=("微软雅黑", LOG_FONT_SIZE), bg=self.MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=self.CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t5.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s5 = ttk.Scrollbar(f5, command=self.t5.yview)
        s5.pack(side=tk.RIGHT, fill=tk.Y)
        self.t5.config(yscrollcommand=s5.set)


        # ========== 中层：t3 昨日强度 | 分时图表容器（新增实时数据行） ==========
        self.mid_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.mid_pane, weight=1)
        # t3
        f3 = tk.Frame(self.mid_pane, bg=self.PANEL_BG, bd=0)
        self.mid_pane.add(f3, weight=11)
        tk.Label(f3, text="昨日强度筛选池", fg=self.TEXT_TITLE, bg=self.PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t3 = tk.Text(f3, font=("微软雅黑", LOG_FONT_SIZE), bg=self.MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=self.CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t3.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s3 = ttk.Scrollbar(f3, command=self.t3.yview)
        s3.pack(side=tk.RIGHT, fill=tk.Y)
        self.t3.config(yscrollcommand=s3.set)
        # 创建 self.t3 后添加
        self.t3.tag_config("tag_break", foreground=self.LINE_PRICEBREAK)    # 蓝
        self.t3.tag_config("tag_fall", foreground=self.LINE_UPDOWN)     # 白
        self.t3.tag_config("tag_top20", foreground=self.LINE_TOP20)    # 黄
        self.t3.tag_config("tag_arbitrage", foreground=self.LINE_ARBITRAGE) # 粉

        # 分时图表外层容器（垂直布局：标题行 → 实时数值行 → 画布）
        chart_wrapper = tk.Frame(self.mid_pane, bg=self.PANEL_BG, bd=0)
        self.mid_pane.add(chart_wrapper, weight=12)
        # 图表标题
        tk.Label(chart_wrapper, text="市场强度分时图",
                 fg=self.TEXT_TITLE, bg=self.PANEL_BG, font=("微软雅黑", TITLE_FONT_SIZE-1, "bold")).pack(anchor="nw", padx=2, pady=1)
        # ========= 新增：实时最新涨跌幅状态栏 =========
        self.chart_status_frame = tk.Frame(chart_wrapper, bg=self.PANEL_BG)
        self.chart_status_frame.pack(fill=tk.X, padx=1.5, pady=0.8)
        # 四个独立标签，分别对应四条曲线配色
        self.label_break = tk.Label(self.chart_status_frame, text="昨量价突破：--%", fg=self.LINE_PRICEBREAK, bg=self.PANEL_BG, font=("微软雅黑",7,"bold"))
        self.label_fall = tk.Label(self.chart_status_frame, text="昨冲高回落：--%", fg=self.LINE_UPDOWN, bg=self.PANEL_BG, font=("微软雅黑",7,"bold"))
        self.label_top20 = tk.Label(self.chart_status_frame, text="今Top20回撤：--%", fg=self.LINE_TOP20, bg=self.PANEL_BG, font=("微软雅黑",7,"bold"))
        self.label_arbitrage = tk.Label(self.chart_status_frame, text="昨小盘套利：--%", fg=self.LINE_ARBITRAGE, bg=self.PANEL_BG, font=("微软雅黑",7,"bold"))
        # 横向均分铺满
        self.label_break.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.label_fall.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.label_top20.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.label_arbitrage.pack(side=tk.LEFT, expand=True, fill=tk.X)
        # 分时画布
        self.chart_canvas = tk.Canvas(chart_wrapper, bg=self.CHART_BG, bd=0, highlightthickness=0)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.chart_canvas.bind("<Configure>", self.on_chart_resize)


        # ========== 下层：t2 冲高回落 | t4 量价齐升 ==========
        bottom_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(bottom_pane, weight=2)
        # t2
        f2 = tk.Frame(bottom_pane, bg=self.PANEL_BG, bd=0)
        bottom_pane.add(f2, weight=1)
        tk.Label(f2, text="冲高回落预警区", fg=self.TEXT_TITLE, bg=self.PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t2 = tk.Text(f2, font=("微软雅黑", LOG_FONT_SIZE), bg=self.MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=self.CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s2 = ttk.Scrollbar(f2, command=self.t2.yview)
        s2.pack(side=tk.RIGHT, fill=tk.Y)
        self.t2.config(yscrollcommand=s2.set)
        # t4
        f4 = tk.Frame(bottom_pane, bg=self.PANEL_BG, bd=0)
        bottom_pane.add(f4, weight=1)
        tk.Label(f4, text="量价齐升突破区", fg=self.TEXT_TITLE, bg=self.PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t4 = tk.Text(f4, font=("微软雅黑", LOG_FONT_SIZE), bg=self.MAIN_BG, fg=self.TEXT_NORMAL,
                          insertbackground=self.CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t4.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s4 = ttk.Scrollbar(f4, command=self.t4.yview)
        s4.pack(side=tk.RIGHT, fill=tk.Y)
        self.t4.config(yscrollcommand=s4.set)

        # ========== 底部：t6 AI异动解析 | t7小盘套利（无改动） ==========
        abnormal_wrapper = tk.Frame(self.main_pane, bg=self.PANEL_BG, height=ABNORMAL_LOG_MIN_HEIGHT, bd=0)
        self.main_pane.add(abnormal_wrapper, weight=0)
        abnormal_wrapper.pack_propagate(False)
        abnormal_h_pane = ttk.PanedWindow(abnormal_wrapper, orient=tk.HORIZONTAL)
        abnormal_h_pane.pack(fill=tk.BOTH, expand=True)
        # t6
        frame_t6 = tk.Frame(abnormal_h_pane, bg=self.PANEL_BG, bd=0)
        abnormal_h_pane.add(frame_t6, weight=1)
        tk.Label(frame_t6, text="AI异动逻辑解析(通义千问)", fg=self.TEXT_TITLE, bg=self.PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t6 = tk.Text(frame_t6, font=("微软雅黑", LOG_FONT_SIZE), bg="#171E2B", fg=self.TEXT_NORMAL,
                          insertbackground=self.CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t6.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s6 = ttk.Scrollbar(frame_t6, command=self.t6.yview)
        s6.pack(side=tk.RIGHT, fill=tk.Y)
        self.t6.config(yscrollcommand=s6.set)
        # t7
        frame_t7 = tk.Frame(abnormal_h_pane, bg=self.PANEL_BG, bd=0)
        abnormal_h_pane.add(frame_t7, weight=1)
        tk.Label(frame_t7, text="小盘套利监控区", fg=self.TEXT_TITLE, bg=self.PANEL_BG,
                 font=("微软雅黑", TITLE_FONT_SIZE, "bold")).pack(anchor="nw", padx=2, pady=1)
        self.t7 = tk.Text(frame_t7, font=("微软雅黑", LOG_FONT_SIZE), bg="#171E2B", fg=self.TEXT_NORMAL,
                          insertbackground=self.CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t7.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1, pady=1)
        s7 = ttk.Scrollbar(frame_t7, command=self.t7.yview)
        s7.pack(side=tk.RIGHT, fill=tk.Y)
        self.t7.config(yscrollcommand=s7.set)

    # ====================== 复盘笔记1布局 ======================
    def build_note_layout_1(self):
        tool_bar = tk.Frame(self.tab_note1, bg=self.PANEL_BG)
        tool_bar.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(tool_bar, text="插入图片", command=self.note1_insert_img, style="Note.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(tool_bar, text="保存笔记", command=self.save_replay_note1, style="Note.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(tool_bar, text="清空全部", command=self.note1_clear_all, style="Note.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(tool_bar, text="导出纯文本", command=self.note1_export_txt, style="Note.TButton").pack(side=tk.LEFT, padx=3)
        #tk.Label(tool_bar, text=f"复盘笔记存储：{NOTE_SAVE_PATH_1}，截图目录：{self.dir_note1}", fg=self.TEXT_TITLE, bg=self.PANEL_BG, font=("微软雅黑",9)).pack(side=tk.RIGHT, padx=10)
        note_wrap = tk.Frame(self.tab_note1, bg=self.MAIN_BG)
        note_wrap.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.note1_text = tk.Text(note_wrap, bg=self.NOTE_BG, fg=self.TEXT_NORMAL, insertbackground=self.CURSOR_COLOR,
                                 font=("微软雅黑",9), wrap=tk.WORD, bd=0)
        self.note1_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        note_scroll = ttk.Scrollbar(note_wrap, command=self.note1_text.yview)
        note_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.note1_text.config(yscrollcommand=note_scroll.set)
        self.note1_text.bind("<<Modified>>", self.on_note1_modify)
        self.note1_text.bind("<Button-3>", self.note1_right_click_menu)
        self.note1_right_menu = tk.Menu(self.root, tearoff=0, bg=self.PANEL_BG, fg=self.TEXT_NORMAL)
        self.note1_right_menu.add_command(label="删除选中图片", command=self.note1_delete_img)

    # ====================== 情绪周期笔记2布局======================
    def build_note_layout_2(self):
        tool_bar = tk.Frame(self.tab_note2, bg=self.PANEL_BG)
        tool_bar.pack(fill=tk.X, padx=4, pady=4)
        ttk.Button(tool_bar, text="插入图片", command=self.note2_insert_img, style="Note.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(tool_bar, text="保存笔记", command=self.save_replay_note2, style="Note.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(tool_bar, text="清空全部", command=self.note2_clear_all, style="Note.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(tool_bar, text="导出纯文本", command=self.note2_export_txt, style="Note.TButton").pack(side=tk.LEFT, padx=3)
        #tk.Label(tool_bar, text=f"情绪周期存储：{NOTE_SAVE_PATH_2}，截图目录：{self.dir_note2}", fg=self.TEXT_TITLE, bg=self.PANEL_BG, font=("微软雅黑",9)).pack(side=tk.RIGHT, padx=10)
        note_wrap = tk.Frame(self.tab_note2, bg=self.MAIN_BG)
        note_wrap.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.note2_text = tk.Text(note_wrap, bg=self.NOTE_BG, fg=self.TEXT_NORMAL, insertbackground=self.CURSOR_COLOR,
                                 font=("微软雅黑",9), wrap=tk.WORD, bd=0)
        self.note2_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        note_scroll = ttk.Scrollbar(note_wrap, command=self.note2_text.yview)
        note_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.note2_text.config(yscrollcommand=note_scroll.set)
        self.note2_text.bind("<<Modified>>", self.on_note2_modify)
        self.note2_text.bind("<Button-3>", self.note2_right_click_menu)
        self.note2_right_menu = tk.Menu(self.root, tearoff=0, bg=self.PANEL_BG, fg=self.TEXT_NORMAL)
        self.note2_right_menu.add_command(label="删除选中图片", command=self.note2_delete_img)

    # ====================== 笔记1 全套逻辑（外置图片文件） ======================
    def on_note1_modify(self, e):
        self.note1_modified = True
        self.note1_text.edit_modified(False)

    def note1_insert_img(self):
        path = filedialog.askopenfilename(title="选择行情截图", filetypes=[("图片文件", "*.jpg;*.png;*.jpeg")])
        if not path:
            return
        try:
            img_raw = Image.open(path)
            max_w = 600
            w, h = img_raw.size
            if w > max_w:
                scale = max_w / w
                img_raw = img_raw.resize((int(w*scale), int(h*scale)), Image.Resampling.LANCZOS)
            # 生成唯一文件名
            self.note1_img_idx += 1
            ext = os.path.splitext(path)[1]
            img_filename = f"n1_{self.note1_img_idx}{ext}"
            save_full_path = self.get_note1_img_path(img_filename)
            # 保存缩放后图片到文件夹
            img_raw.save(save_full_path)
            # 生成tk图片缓存
            tk_img = ImageTk.PhotoImage(img_raw)
            key = f"n1_img_{self.note1_img_idx}"
            self.note1_images[key] = tk_img
            # 插入文本框
            self.note1_text.image_create(tk.INSERT, image=tk_img, name=key)
            self.note1_text.insert(tk.INSERT, "\n")
            self.note1_modified = True
        except Exception as e:
            messagebox.showerror("图片加载失败", str(e))

    def note1_right_click_menu(self, e):
        self.n1_click_pos = self.note1_text.index(f"@{e.x},{e.y}")
        if self.note1_text.image_cget(self.n1_click_pos, "image"):
            self.note1_right_menu.tk_popup(e.x_root, e.y_root)

    def note1_delete_img(self):
        try:
            img_name = self.note1_text.image_cget(self.n1_click_pos, "image")
            # 从文本框删除图片元素
            self.note1_text.delete(self.n1_click_pos, f"{self.n1_click_pos}+1c")
            # 从缓存移除
            if img_name in self.note1_images:
                del self.note1_images[img_name]
            # 删除磁盘图片文件
            img_idx = int(img_name.split("_")[-1])
            # 遍历目录匹配前缀删除
            for fname in os.listdir(self.dir_note1):
                if fname.startswith(f"n1_{img_idx}."):
                    fpath = self.get_note1_img_path(fname)
                    if os.path.exists(fpath):
                        os.remove(fpath)
            self.note1_modified = True
        except Exception as err:
            print("删除图片失败：", err)

    def note1_clear_all(self):
        if messagebox.askyesno("确认清空", "删除笔记1全部文字与图片？磁盘图片文件也会删除！"):
            self.note1_text.delete("1.0", tk.END)
            self.note1_images.clear()
            # 清空磁盘note1图片文件夹
            for fname in os.listdir(self.dir_note1):
                fpath = self.get_note1_img_path(fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            self.note1_modified = True

    def note1_export_txt(self):
        txt = self.note1_text.get("1.0", tk.END)
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("文本", "*.txt")], title="导出笔记1文本")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(txt)
            messagebox.showinfo("导出完成", "笔记1文本已导出")

    def save_replay_note1(self):
        text = self.note1_text.get("1.0", tk.END)
        img_list = []
        dump = self.note1_text.dump("1.0", tk.END, window=True)
        for pos, typ, name in dump:
            if typ == "image":
                img_idx = int(name.split("_")[-1])
                # 查找对应图片文件名
                target_file = None
                for fname in os.listdir(self.dir_note1):
                    if fname.startswith(f"n1_{img_idx}."):
                        target_file = fname
                        break
                if target_file:
                    img_list.append({"pos": pos, "key": name, "file": target_file})
        data = {
            "text": text,
            "img_list": img_list,
            "img_idx": self.note1_img_idx
        }
        with open(NOTE_SAVE_PATH_1, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.note1_modified = False
        messagebox.showinfo("保存成功", "复盘笔记已保存")

    def load_replay_note1(self):
        if not os.path.exists(NOTE_SAVE_PATH_1):
            return
        try:
            with open(NOTE_SAVE_PATH_1, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.note1_text.delete("1.0", tk.END)
            self.note1_text.insert("1.0", d.get("text", ""))
            self.note1_img_idx = d.get("img_idx", 0)
            self.note1_images.clear()
            # 恢复所有图片
            for img_info in d.get("img_list", []):
                pos = img_info["pos"]
                key = img_info["key"]
                filename = img_info["file"]
                img_full_path = self.get_note1_img_path(filename)
                if not os.path.exists(img_full_path):
                    continue
                pil_img = Image.open(img_full_path)
                tk_img = ImageTk.PhotoImage(pil_img)
                self.note1_images[key] = tk_img
                self.note1_text.image_create(pos, image=tk_img, name=key)
            self.note1_modified = False
        except Exception as e:
            print("加载笔记1失败：", e)

    # ====================== 笔记2 全套逻辑（外置图片文件） ======================
    def on_note2_modify(self, e):
        self.note2_modified = True
        self.note2_text.edit_modified(False)

    def note2_insert_img(self):
        path = filedialog.askopenfilename(title="选择行情截图", filetypes=[("图片文件", "*.jpg;*.png;*.jpeg")])
        if not path:
            return
        try:
            img_raw = Image.open(path)
            max_w = 600
            w, h = img_raw.size
            if w > max_w:
                scale = max_w / w
                img_raw = img_raw.resize((int(w*scale), int(h*scale)), Image.Resampling.LANCZOS)
            self.note2_img_idx += 1
            ext = os.path.splitext(path)[1]
            img_filename = f"n2_{self.note2_img_idx}{ext}"
            save_full_path = self.get_note2_img_path(img_filename)
            img_raw.save(save_full_path)
            tk_img = ImageTk.PhotoImage(img_raw)
            key = f"n2_img_{self.note2_img_idx}"
            self.note2_images[key] = tk_img
            self.note2_text.image_create(tk.INSERT, image=tk_img, name=key)
            self.note2_text.insert(tk.INSERT, "\n")
            self.note2_modified = True
        except Exception as e:
            messagebox.showerror("图片加载失败", str(e))

    def note2_right_click_menu(self, e):
        self.n2_click_pos = self.note2_text.index(f"@{e.x},{e.y}")
        if self.note2_text.image_cget(self.n2_click_pos, "image"):
            self.note2_right_menu.tk_popup(e.x_root, e.y_root)

    def note2_delete_img(self):
        try:
            img_name = self.note2_text.image_cget(self.n2_click_pos, "image")
            self.note2_text.delete(self.n2_click_pos, f"{self.n2_click_pos}+1c")
            if img_name in self.note2_images:
                del self.note2_images[img_name]
            img_idx = int(img_name.split("_")[-1])
            for fname in os.listdir(self.dir_note2):
                if fname.startswith(f"n2_{img_idx}."):
                    fpath = self.get_note2_img_path(fname)
                    if os.path.exists(fpath):
                        os.remove(fpath)
            self.note2_modified = True
        except Exception as err:
            print("删除图片失败：", err)

    def note2_clear_all(self):
        if messagebox.askyesno("确认清空", "删除情绪周期全部文字与图片？磁盘图片文件也会删除！"):
            self.note2_text.delete("1.0", tk.END)
            self.note2_images.clear()
            for fname in os.listdir(self.dir_note2):
                fpath = self.get_note2_img_path(fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            self.note2_modified = True

    def note2_export_txt(self):
        txt = self.note2_text.get("1.0", tk.END)
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("文本", "*.txt")], title="导出笔记2文本")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(txt)
            messagebox.showinfo("导出完成", "笔记2文本已导出")

    def save_replay_note2(self):
        text = self.note2_text.get("1.0", tk.END)
        img_list = []
        dump = self.note2_text.dump("1.0", tk.END, window=True)
        for pos, typ, name in dump:
            if typ == "image":
                img_idx = int(name.split("_")[-1])
                target_file = None
                for fname in os.listdir(self.dir_note2):
                    if fname.startswith(f"n2_{img_idx}."):
                        target_file = fname
                        break
                if target_file:
                    img_list.append({"pos": pos, "key": name, "file": target_file})
        data = {
            "text": text,
            "img_list": img_list,
            "img_idx": self.note2_img_idx
        }
        with open(NOTE_SAVE_PATH_2, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.note2_modified = False
        messagebox.showinfo("保存成功", "情绪周期已保存")

    def load_replay_note2(self):
        if not os.path.exists(NOTE_SAVE_PATH_2):
            return
        try:
            with open(NOTE_SAVE_PATH_2, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.note2_text.delete("1.0", tk.END)
            self.note2_text.insert("1.0", d.get("text", ""))
            self.note2_img_idx = d.get("img_idx", 0)
            self.note2_images.clear()
            for img_info in d.get("img_list", []):
                pos = img_info["pos"]
                key = img_info["key"]
                filename = img_info["file"]
                img_full_path = self.get_note2_img_path(filename)
                if not os.path.exists(img_full_path):
                    continue
                pil_img = Image.open(img_full_path)
                tk_img = ImageTk.PhotoImage(pil_img)
                self.note2_images[key] = tk_img
                self.note2_text.image_create(pos, image=tk_img, name=key)
            self.note2_modified = False
        except Exception as e:
            print("加载笔记2失败：", e)
    # ====================== 原有工具、绘图、日志读取函数（新增更新状态栏代码） ======================
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
        arbitrage_reg = re.compile(r'小市值套利.*?([+-]?\d+\.?\d+)%')
        curr_time = None
        brk_val = None
        fall_val = None
        top_val = None
        arb_val = 0.0  # 无匹配时默认0，不阻塞数据存储
        for line in lines:
            line = line.strip()
            if not line:
                continue
            t_match = time_reg.search(line)
            if t_match:
                # 仅校验原有三个必填指标，套利字段可选
                if curr_time and brk_val is not None and fall_val is not None and top_val is not None:
                    temp_dict[curr_time] = (brk_val, fall_val, top_val, arb_val)
                curr_time = t_match.group(1)
                brk_val = fall_val = top_val = None
                arb_val = 0.0
            bm = break_reg.search(line)
            if bm:
                brk_val = float(bm.group(1))
            fm = fall_reg.search(line)
            if fm:
                fall_val = float(fm.group(1))
            tm = top20_reg.search(line)
            if tm:
                top_val = float(tm.group(1))
            am = arbitrage_reg.search(line)
            if am:
                arb_val = float(am.group(1))
        # 保存最后一组时间切片
        if curr_time and brk_val is not None and fall_val is not None and top_val is not None:
            temp_dict[curr_time] = (brk_val, fall_val, top_val, arb_val)
        # 组装绘图数据元组
        for tm_str, (b, f, t, a) in temp_dict.items():
            minute = self.time_to_minute(tm_str)
            if MORNING_START <= minute <= AFTER_END:
                res.append((minute, tm_str, b, f, t, a))
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
    # ========= 新增：更新顶部实时涨跌幅状态栏 =========
    def update_chart_status_label(self):
        if not self.chart_data:
            self.label_break.config(text="昨量价突破：--%")
            self.label_fall.config(text="昨冲高回落：--%")
            self.label_top20.config(text="今Top20回撤：--%")
            self.label_arbitrage.config(text="昨小盘套利：--%")
            return
        # 取最后一条最新分时数据
        latest = self.chart_data[-1]
        _, tm_str, break_rate, fall_rate, top20_dd, arbitrage_rate = latest
        self.label_break.config(text=f"昨量价突破：{break_rate:.2f}%")
        self.label_fall.config(text=f"昨冲高回落：{fall_rate:.2f}%")
        self.label_top20.config(text=f"今Top20回撤：{top20_dd:.2f}%")
        self.label_arbitrage.config(text=f"昨小盘套利：{arbitrage_rate:.2f}%")
    def draw_chart(self):
        # 每次绘图同步刷新顶部实时数值
        self.update_chart_status_label()
        canvas = self.chart_canvas
        cw = canvas.winfo_width()
        ch = canvas.winfo_height()
        if cw < 50 or ch < 50:
            canvas.delete("chart_item")
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
            y_arbitrage = [d[5] for d in self.chart_data]
            y_all = y_break + y_fall + y_top20 + y_arbitrage
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
        # 四条曲线绘制
        if len(self.chart_data) >= 2:
            # 1.蓝线：量价突破
            pts = [(time_to_valid_x(d[0]), v2y(d[2])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_PRICEBREAK, width=LINE_WIDTH, tag="chart_item")
            # 2.白线：冲高回落
            pts = [(time_to_valid_x(d[0]), v2y(d[3])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_UPDOWN, width=LINE_WIDTH+0.2, tag="chart_item")
            # 3.黄线：Top20均价回撤
            pts = [(time_to_valid_x(d[0]), v2y(d[4])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_TOP20, width=LINE_WIDTH, tag="chart_item")
            # 4.粉色线：小盘套利平均涨幅
            pts = [(time_to_valid_x(d[0]), v2y(d[5])) for d in self.chart_data]
            for i in range(len(pts)-1):
                canvas.create_line(pts[i][0],pts[i][1],pts[i+1][0],pts[i+1][1], fill=self.LINE_ARBITRAGE, width=LINE_WIDTH, tag="chart_item")
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
            #临时注释，不要删除
            #tip_x = 150
            #tip_y = ch - 30
            #warn_text = f"资金出逃嫌疑，切新题材或打首板，小市值"
            #txt_w = len(warn_text) * 10
            #txt_h = 12
            #canvas.create_rectangle(tip_x-txt_w/2-4, tip_y-txt_h/2-2, tip_x+txt_w/2+4, tip_y+txt_h/2+2,
            #                         fill="", outline=self.FALL_GREEN, width=1, dash=(3,3), tag="chart_item")
            #canvas.create_text(tip_x, tip_y, text=warn_text, fill=self.FALL_GREEN, font=("微软雅黑",LOG_FONT_SIZE,"bold"), anchor=tk.CENTER, tag="chart_item")
            #canvas.create_line(tip_x, tip_y-txt_h/2-2, risk_x, risk_y+3, fill=self.FALL_GREEN, width=1.2, dash=(3,3), arrow=tk.FIRST, tag="chart_item")
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
            #临时注释，不要删除
            #tip_x = pad + inner_w * 0.4
            #tip_y = pad + inner_h * 0.1
            #warn_text = "昨量价齐升超预期" if VolPriceBreak_up_or_down==1 else f"昨量价齐升不及预期"
            #txt_len = len(warn_text) * 10
            #canvas.create_rectangle(tip_x - txt_len/2 - 4, tip_y - 8, tip_x + txt_len/2 + 4, tip_y + 8,
            #                 fill="", outline=VolPriceBreak_Color, width=1, dash=(3,3), tag="chart_item")
            #canvas.create_text(tip_x, tip_y, text=warn_text, fill=VolPriceBreak_Color, font=("微软雅黑",LOG_FONT_SIZE,"bold"), anchor=tk.CENTER, tag="chart_item")
            #canvas.create_line(tip_x, tip_y + 10, risk_x, risk_y + 3, fill=VolPriceBreak_Color, width=1.2, dash=(3,3), arrow=tk.FIRST, tag="chart_item")
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
            #临时注释，不要删除
            #tip_x = 420
            #tip_y = ch - 32
            #warn_text = f"昨冲高回落超预期" if CommonDrawdown_up_or_down==1 else f"昨冲高回落资金割肉，恐慌情绪蔓延"
            #txt_w = len(warn_text) * 10
            #canvas.create_rectangle(tip_x-txt_w/2-4, tip_y-8, tip_x+txt_w/2+4, tip_y+8, fill="", outline=CommonDrawdown_Color, width=1, dash=(3,3), tag="chart_item")
            #canvas.create_text(tip_x, tip_y, text=warn_text, fill=CommonDrawdown_Color, font=("微软雅黑",LOG_FONT_SIZE,"bold"), anchor=tk.CENTER, tag="chart_item")
            #canvas.create_line(tip_x, tip_y-10, risk_x, risk_y+3, fill=CommonDrawdown_Color, width=1.2, dash=(3,3), arrow=tk.FIRST, tag="chart_item")
        if self.mouse_in_chart:
            self.draw_cross_line(self.mouse_x, self.mouse_y)

    def draw_cross_line(self, x, y):
        pad, bottom, right, top = self._inner_rect
        self.chart_canvas.delete(self.cross_tag)
        if pad < x < right and top < y < bottom:
            self.chart_canvas.create_line(x, top, x, bottom, fill=CROSS_LINE_COLOR,dash=CROSS_DASH_STYLE, width=1, tag=self.cross_tag)
            self.chart_canvas.create_line(pad, y, right, y, fill=CROSS_LINE_COLOR,dash=CROSS_DASH_STYLE, width=1, tag=self.cross_tag)
    # ====================== 鼠标悬浮提示（增加套利数值展示，弹窗尺寸适配） ======================
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
        _, hhmm, break_rate, fall_rate, top20_dd, arbitrage_rate = near_data
        text = (f"交易时间：{hhmm}\n"
                f"蓝-昨量价突破：{break_rate:.2f}%\n"
                f"白-昨冲高回落：{fall_rate:.2f}%\n"
                f"黄-Top20回撤：{top20_dd:.2f}%\n"
                f"粉-昨小盘套利：{arbitrage_rate:.2f}%")
        self.tip_label.config(text=text)
        win_x = self.chart_canvas.winfo_rootx() + x + 18
        win_y = self.chart_canvas.winfo_rooty() + y + 18
        w, h = 175, 90
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
    # ====================== 日志窗口读取、滚动、线程逻辑完全不变 ======================
    def limit_log_lines(self, text_widget):
        cnt = int(text_widget.index(tk.END).split('.')[0])
        if cnt > MAX_LOG_LINES:
            text_widget.delete("1.0", f"{cnt-MAX_LOG_LINES}.0")

    def bind_scroll_event(self):
        boxes = [self.t1, self.t2, self.t3, self.t4, self.t5, self.t6, self.t7]
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
            for w in [self.t1, self.t2, self.t3, self.t4, self.t5, self.t6, self.t7]:
                w.config(state=tk.DISABLED)
        def end(_):
            for w in [self.t1, self.t2, self.t3, self.t4, self.t5, self.t6, self.t7]:
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
    def log_arbitrage(self, msg):self.safe_append_log(self.t7, msg)
    def get_text_widget(self, k):
        m = {"t1":self.t1,"t2":self.t2,"t3":self.t3,"t4":self.t4,"t5":self.t5,"t6":self.t6,"t7":self.t7}
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
                        if key == "t3":
                            # 按分组批量上色：标题+同组股票统一颜色
                            lines = cont.splitlines(True)
                            line_with_tag = self.parse_t3_group_lines(lines)
                            for l, tag in line_with_tag:
                                if tag:
                                    wd.insert(tk.END, l, tag)
                                else:
                                    wd.insert(tk.END, l)
                        else:
                            # 其余日志窗口保持原有纯色
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
        # 退出前自动保存两份笔记
        if self.note1_modified:
            self.save_replay_note1()
        if self.note2_modified:
            self.save_replay_note2()
        if self.tip_win:
            self.tip_win.destroy()
        self.chart_canvas.delete(self.cross_tag)

# ====================== 程序入口 ======================
if __name__ == "__main__":
    try:
        from PIL import Image, ImageTk
    except ImportError:
        print("缺少图片依赖库，请执行：pip install pillow")
        sys.exit(1)
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