import tkinter as tk
from tkinter import ttk
import time
import threading
import os
import sys
import re

# 配置项
MAX_LOG_LINES = 60         #区域日志条数
RESUME_FOLLOW_DELAY = 3.0  # 静置n秒自动恢复自动跟随
LOG_FONT_SIZE = 8         # 日志内容字体大小
TITLE_FONT_SIZE = 9       # 分区标题字体大小
LOG_POLL_INTERVAL = 0.2   # 日志文件轮询间隔(秒)
CHART_REFRESH_INTERVAL = 0.3 # 分时图刷新间隔
CHART_PADDING = 30        # 图表边距
LINE_WIDTH = 0.5            # 统一线条宽度

# A股交易时间 分钟数
MORNING_START = 570    # 09:30
MORNING_END = 690      # 11:30
AFTER_START = 780      # 13:00
AFTER_END = 900        # 15:00

# ========== 固定：获取【脚本所在目录】所有日志都放这里 ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

# 日志文件名映射
LOG_FILE_NAME_MAP = {
    "t1": "Log_PositionStock.txt",          # 持仓监控区
    "t2": "Log_CommonDrawdown.txt",        # 冲高回落区
    "t3": "Log_StockStrengthYesterday.txt", # 昨日筛选区(分时图数据源)
    "t4": "Log_VolPriceBreak.txt",          # 量价齐升区
    "t5": "Log_StrongStock.txt"            # 强势监控区(左日志+右图表)
}

# 拼接成完整绝对路径（全部在脚本同级目录）
LOG_FILE_MAP = {
    k: os.path.join(SCRIPT_DIR, v) for k, v in LOG_FILE_NAME_MAP.items()
}

# 正则匹配日志格式：[时分] 突破涨幅,回落涨幅
DATA_PATTERN = re.compile(r'\[(\d{2}:\d{2})\]\s*([\d.-]+),([\d.-]+)')

class QuantLogPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("监控面板")
        self.root.geometry("1200x720")
        self.root.resizable(True, True)
        BG_COLOR = "#000000"
        FG_COLOR = "#cccccc"
        CURSOR_COLOR = "#cccccc"
        CHART_BG = "#0a0a0a"
        # 配色：量价突破灰色实线，冲高回落白色实线
        LINE_GRAY = "#888888"
        LINE_WHITE = "#ffffff"
        AXIS_COLOR = "#444444"
        TEXT_CHART_COLOR = "#aaaaaa"

        self.BG_COLOR = BG_COLOR
        self.FG_COLOR = FG_COLOR
        self.CHART_BG = CHART_BG
        self.LINE_GRAY = LINE_GRAY
        self.LINE_WHITE = LINE_WHITE
        self.AXIS_COLOR = AXIS_COLOR
        self.TEXT_CHART_COLOR = TEXT_CHART_COLOR

        self.manual_view = False
        self.last_scroll_time = 0
        self.file_read_pos = {k: 0 for k in LOG_FILE_MAP.keys()}
        self.running_flag = True
        self.chart_data = []
        self.last_chart_update = 0

        self.root.configure(bg=BG_COLOR)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TPanedWindow", background=BG_COLOR, borderwidth=0)
        style.configure("TScrollbar", background=BG_COLOR, troughcolor=BG_COLOR, borderwidth=0, relief=tk.FLAT)
        style.map("TScrollbar", background=[("active", BG_COLOR), ("pressed", BG_COLOR)])

        self.main_pane = ttk.PanedWindow(root, orient=tk.VERTICAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # 上层双区
        self.top_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.top_pane, weight=2)
        f1 = tk.Frame(self.top_pane, bg=BG_COLOR, bd=0)
        self.top_pane.add(f1, weight=1)
        tk.Label(f1, text="持仓监控区", fg=FG_COLOR, bg=BG_COLOR, font=("Consolas",TITLE_FONT_SIZE,"bold")).pack(anchor="nw", padx=2)
        self.t1 = tk.Text(f1, font=("Consolas",LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR, insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s1 = ttk.Scrollbar(f1, command=self.t1.yview)
        s1.pack(side=tk.RIGHT, fill=tk.Y)
        self.t1.config(yscrollcommand=s1.set)

        f2 = tk.Frame(self.top_pane, bg=BG_COLOR, bd=0)
        self.top_pane.add(f2, weight=1)
        tk.Label(f2, text="冲高回落区", fg=FG_COLOR, bg=BG_COLOR, font=("Consolas",TITLE_FONT_SIZE,"bold")).pack(anchor="nw", padx=2)
        self.t2 = tk.Text(f2, font=("Consolas",LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR, insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s2 = ttk.Scrollbar(f2, command=self.t2.yview)
        s2.pack(side=tk.RIGHT, fill=tk.Y)
        self.t2.config(yscrollcommand=s2.set)

        # 中层双区
        self.mid_pane = ttk.PanedWindow(self.main_pane, orient=tk.HORIZONTAL)
        self.main_pane.add(self.mid_pane, weight=2)
        f3 = tk.Frame(self.mid_pane, bg=BG_COLOR, bd=0)
        self.mid_pane.add(f3, weight=1)
        tk.Label(f3, text="昨日筛选区", fg=FG_COLOR, bg=BG_COLOR, font=("Consolas",TITLE_FONT_SIZE,"bold")).pack(anchor="nw", padx=2)
        self.t3 = tk.Text(f3, font=("Consolas",LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR, insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t3.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s3 = ttk.Scrollbar(f3, command=self.t3.yview)
        s3.pack(side=tk.RIGHT, fill=tk.Y)
        self.t3.config(yscrollcommand=s3.set)

        f4 = tk.Frame(self.mid_pane, bg=BG_COLOR, bd=0)
        self.mid_pane.add(f4, weight=1)
        tk.Label(f4, text="量价齐升区", fg=FG_COLOR, bg=BG_COLOR, font=("Consolas",TITLE_FONT_SIZE,"bold")).pack(anchor="nw", padx=2)
        self.t4 = tk.Text(f4, font=("Consolas",LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR, insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t4.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s4 = ttk.Scrollbar(f4, command=self.t4.yview)
        s4.pack(side=tk.RIGHT, fill=tk.Y)
        self.t4.config(yscrollcommand=s4.set)

        # 下层强势监控区 左右布局
        bottom_main = tk.Frame(self.main_pane, bg=BG_COLOR)
        self.main_pane.add(bottom_main, weight=2)
        bottom_pane = ttk.PanedWindow(bottom_main, orient=tk.HORIZONTAL)
        bottom_pane.pack(fill=tk.BOTH, expand=True)

        left_log_frame = tk.Frame(bottom_pane, bg=BG_COLOR)
        bottom_pane.add(left_log_frame, weight=1)
        tk.Label(left_log_frame, text="强势监控区", fg=FG_COLOR, bg=BG_COLOR, font=("Consolas",TITLE_FONT_SIZE,"bold")).pack(anchor="nw", padx=2)
        self.t5 = tk.Text(left_log_frame, font=("Consolas",LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR, insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t5.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s5 = ttk.Scrollbar(left_log_frame, command=self.t5.yview)
        s5.pack(side=tk.RIGHT, fill=tk.Y)
        self.t5.config(yscrollcommand=s5.set)

        chart_frame = tk.Frame(bottom_pane, bg=BG_COLOR)
        bottom_pane.add(chart_frame, weight=1)
        tk.Label(chart_frame, text="昨筛选强度分时图(灰线=昨量价突破 白线=昨冲高回落)", fg=FG_COLOR, bg=BG_COLOR, font=("Consolas",TITLE_FONT_SIZE,"bold")).pack(anchor="nw", padx=2)
        self.chart_canvas = tk.Canvas(chart_frame, bg=CHART_BG, bd=0, highlightthickness=0)
        self.chart_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chart_canvas.bind("<Configure>", self.on_chart_resize)

        self.bind_scroll_event()
        self.bind_drag_event()
        self.start_file_monitor_threads()
        self.start_chart_refresh_loop()

    def time_to_minute(self, time_str):
        h, m = map(int, time_str.split(":"))
        return h * 60 + m

    def parse_log_chart_data(self, log_content):
        res = []
        lines = log_content.splitlines()
        # 存储当前一组的时间、两个均值
        curr_hhmm = None
        avg_break_val = None
        avg_fall_val = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 1. 匹配头部时间行：—————————— 2026-06-30 09:31 昨筛选强度监控 ——————————
            import re
            time_pat = re.compile(r'(\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2}))')
            time_match = time_pat.search(line)
            if time_match:
                curr_hhmm = time_match.group(2)  # 只拿到 09:31
                continue

            # 2. 匹配昨量价突破组平均涨幅
            break_pat = re.compile(r'【昨量价突破组】.*?平均涨幅[:：]\s*([+-]?\d+\.?\d*)%')
            bm = break_pat.search(line)
            if bm and curr_hhmm:
                avg_break_val = float(bm.group(1))
                continue

            # 3. 匹配昨冲高回落组平均涨幅
            fall_pat = re.compile(r'【昨冲高回落组】.*?平均涨幅[:：]\s*([+-]?\d+\.?\d*)%')
            fm = fall_pat.search(line)
            if fm and curr_hhmm:
                avg_fall_val = float(fm.group(1))
                # 两个均值都凑齐，组装一条数据
                if avg_break_val is not None and avg_fall_val is not None:
                    minute = self.time_to_minute(curr_hhmm)
                    # 过滤午休无效时段 11:31 ~ 12:59
                    if (MORNING_START <= minute <= MORNING_END) or (AFTER_START <= minute <= AFTER_END):
                        res.append((minute, curr_hhmm, avg_break_val, avg_fall_val))
                    # 重置，等待下一组新数据
                    curr_hhmm = None
                    avg_break_val = None
                    avg_fall_val = None

        # 按时间升序排序
        return sorted(res, key=lambda x: x[0])

    def update_chart_cache(self, new_data_list):
        exist_keys = set((d[0],d[1]) for d in self.chart_data)
        for item in new_data_list:
            if (item[0],item[1]) not in exist_keys:
                self.chart_data.append(item)
        if len(self.chart_data) > 300:
            self.chart_data = self.chart_data[-300:]

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

        # 有效总时长：早盘120分钟 + 下午120分钟
        total_valid_len = (MORNING_END - MORNING_START) + (AFTER_END - AFTER_START)

        # Y轴自适应
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

        canvas.delete("all")
        canvas.create_line(pad, pad, pad, ch-pad, fill=self.AXIS_COLOR, width=1)
        canvas.create_line(pad, ch-pad, cw-pad, ch-pad, fill=self.AXIS_COLOR, width=1)

        # 时间映射函数：跳过午休空白
        def get_x_pos(min_val):
            if MORNING_START <= min_val <= MORNING_END:
                offset = min_val - MORNING_START
            else:
                offset = (MORNING_END - MORNING_START) + (min_val - AFTER_START)
            return pad + (offset / total_valid_len) * inner_w

        # 坐标Y
        def get_y_pos(val):
            return ch - pad - ((val - min_y) / (max_y - min_y)) * inner_h

        # 分割线：早盘结束位置
        split_x = get_x_pos(MORNING_END)
        canvas.create_line(split_x, pad, split_x, ch-pad, fill="#333333", width=1, dash=(3,3))

        # X轴刻度只显示4个有效时间
        tick_list = [
            (MORNING_START, "09:30"),
            (MORNING_END, "11:30"),
            (AFTER_START, "13:00"),
            (AFTER_END, "15:00")
        ]
        for tm_val, txt in tick_list:
            px = get_x_pos(tm_val)
            canvas.create_text(px, ch-pad+12, text=txt, fill=self.TEXT_CHART_COLOR, font=("Consolas",7))

        # Y网格
        y_step = (max_y - min_y) / 5
        for i in range(6):
            yv = min_y + y_step * i
            yp = get_y_pos(yv)
            canvas.create_line(pad, yp, cw-pad, yp, fill="#222222", width=1)
            canvas.create_text(pad-5, yp, text=f"{yv:.1f}", fill=self.TEXT_CHART_COLOR, font=("Consolas",7), anchor=tk.E)

        # 0轴
        zero_y = get_y_pos(0)
        if pad < zero_y < ch-pad:
            canvas.create_line(pad, zero_y, cw-pad, zero_y, fill="#555555", width=1, dash=(2,2))

        # 绘制灰线 量价突破
        if len(self.chart_data)>=2:
            pts1 = [(get_x_pos(d[0]), get_y_pos(d[2])) for d in self.chart_data]
            for i in range(len(pts1)-1):
                x1,y1=pts1[i]
                x2,y2=pts1[i+1]
                canvas.create_line(x1,y1,x2,y2, fill=self.LINE_GRAY, width=LINE_WIDTH)

        # 绘制白线 冲高回落
        if len(self.chart_data)>=2:
            pts2 = [(get_x_pos(d[0]), get_y_pos(d[3])) for d in self.chart_data]
            for i in range(len(pts2)-1):
                x1,y1=pts2[i]
                x2,y2=pts2[i+1]
                canvas.create_line(x1,y1,x2,y2, fill=self.LINE_WHITE, width=LINE_WIDTH)

    def on_chart_resize(self, event):
        self.draw_chart()

    def start_chart_refresh_loop(self):
        def loop():
            while self.running_flag:
                time.sleep(CHART_REFRESH_INTERVAL)
                self.root.after_idle(self.draw_chart)
        threading.Thread(target=loop, daemon=True).start()

    def limit_log_lines(self, text_widget):
        cnt = int(text_widget.index(tk.END).split('.')[0])
        if cnt > MAX_LOG_LINES:
            text_widget.delete("1.0", f"{cnt-MAX_LOG_LINES}.0")

    def bind_scroll_event(self):
        boxes = [self.t1,self.t2,self.t3,self.t4,self.t5]
        def cb(e):
            self.manual_view=True
            self.last_scroll_time=time.time()
        for b in boxes:
            b.bind("<MouseWheel>",cb)

    def safe_append_log(self, wd, msg):
        def inner():
            t=time.strftime("%H:%M:%S")
            wd.insert(tk.END,f"[{t}] {msg}\n")
            self.limit_log_lines(wd)
            if self.manual_view and time.time()-self.last_scroll_time>RESUME_FOLLOW_DELAY:
                self.manual_view=False
            if not self.manual_view:
                wd.see(tk.END)
        self.root.after_idle(inner)

    def bind_drag_event(self):
        def start(_):
            for w in [self.t1,self.t2,self.t3,self.t4,self.t5]:
                w.config(state=tk.DISABLED)
        def end(_):
            for w in [self.t1,self.t2,self.t3,self.t4,self.t5]:
                w.config(state=tk.NORMAL)
        for p in [self.top_pane,self.mid_pane,self.main_pane]:
            p.bind("<ButtonPress-1>",start)
            p.bind("<ButtonRelease-1>",end)

    def log_warn(self,msg):self.safe_append_log(self.t1,msg)
    def log_strong(self,msg):self.safe_append_log(self.t2,msg)
    def log_market(self,msg):self.safe_append_log(self.t3,msg)
    def log_position(self,msg):self.safe_append_log(self.t4,msg)
    def log_system(self,msg):self.safe_append_log(self.t5,msg)

    def get_text_widget(self,k):
        m={"t1":self.t1,"t2":self.t2,"t3":self.t3,"t4":self.t4,"t5":self.t5}
        return m.get(k)

    def single_file_monitor(self,key,path):
        pos=self.file_read_pos[key]
        wd=self.get_text_widget(key)
        while self.running_flag:
            try:
                if not os.path.exists(path):
                    time.sleep(LOG_POLL_INTERVAL)
                    continue
                with open(path,"r",encoding="utf-8",errors="ignore") as f:
                    f.seek(pos)
                    lines=f.readlines()
                    pos=f.tell()
                    self.file_read_pos[key]=pos
                if lines:
                    cont="".join(lines)
                    if key=="t3":
                        arr=self.parse_log_chart_data(cont)
                        self.update_chart_cache(arr)
                    def ui_up():
                        wd.insert(tk.END,cont)
                        self.limit_log_lines(wd)
                        if self.manual_view and time.time()-self.last_scroll_time>RESUME_FOLLOW_DELAY:
                            self.manual_view=False
                        if not self.manual_view:
                            wd.see(tk.END)
                    self.root.after_idle(ui_up)
            except:
                pass
            time.sleep(LOG_POLL_INTERVAL)

    def start_file_monitor_threads(self):
        for k,p in LOG_FILE_MAP.items():
            threading.Thread(target=self.single_file_monitor,args=(k,p),daemon=True).start()

    def close_all_monitor(self):
        self.running_flag=False

# 模拟测试数据
# 新版模拟写入：完全仿真真实日志格式
def mock_market_data_writer():
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
        if cur_min > AFTER_END:
            cur_min = MORNING_START
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("")

        # 拼接时分
        hh = cur_min // 60
        mm = cur_min % 60
        hhmm_str = f"{hh:02d}:{mm:02d}"
        date_str = "2026-06-30"

        # 模拟两组平均涨幅
        val_break = round(random.uniform(-2.5, 6.5), 2)
        val_drop = round(random.uniform(-5.5, 3.0), 2)

        # 构造和真实一模一样的日志文本
        log_text = f"""—————————— {date_str} {hhmm_str} 昨筛选强度监控 ——————————
【昨量价突破组】共6只 | 平均涨幅：{val_break}%
机器人　  8.12% | 聚和材料  3.04% | 荣昌生物  2.14%
金宏气体  6.10% | 广钢气体  2.45% | 贝达药业 -0.37%
【昨冲高回落组】共43只 | 平均涨幅：{val_drop}%
晶瑞电材  5.72% | 宏景科技  0.34% | 铂科新材 -1.16% | 东方钽业 -2.51%
昊华科技  4.70% | 澜起科技  0.20% | 江钨装备 -1.31% | 飞凯材料 -2.80%

"""
        # 追加写入日志文件
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_text)

        cur_min += 1
        time.sleep(0.6)



if __name__ == "__main__":
    root=tk.Tk()
    app=QuantLogPanel(root)
    def on_close():
        app.close_all_monitor()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW",on_close)

    #threading.Thread(target=mock_market_data_writer,daemon=True).start()
    root.mainloop()