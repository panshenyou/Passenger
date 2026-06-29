import tkinter as tk
from tkinter import ttk
import time
import threading
import os
import sys

# 配置项
MAX_LOG_LINES = 60         #区域日志条数
RESUME_FOLLOW_DELAY = 3.0  # 静置n秒自动恢复自动跟随
LOG_FONT_SIZE = 8         # 日志内容字体大小
TITLE_FONT_SIZE = 9       # 分区标题字体大小
LOG_POLL_INTERVAL = 0.2   # 日志文件轮询间隔(秒)

# ========== 固定：获取【脚本所在目录】所有日志都放这里 ==========
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

# 日志文件名映射
LOG_FILE_NAME_MAP = {
    "t1": "Log_PositionStock.txt",          # 持仓监控区
    "t2": "Log_CommonDrawdown.txt",        # 冲高回落区
    "t3": "Log_StockStrengthYesterday.txt", # 昨日筛选区
    "t4": "Log_VolPriceBreak.txt",          # 量价齐升区
    "t5": "Log_StrongStock.txt"            # 强势监控区
}

# 拼接成完整绝对路径（全部在脚本同级目录）
LOG_FILE_MAP = {
    k: os.path.join(SCRIPT_DIR, v) for k, v in LOG_FILE_NAME_MAP.items()
}

class QuantLogPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("监控面板")
        self.root.geometry("1200x720")
        self.root.resizable(True, True)
        BG_COLOR = "#000000"
        FG_COLOR = "#cccccc"
        CURSOR_COLOR = "#cccccc"

        self.manual_view = False
        self.last_scroll_time = 0

        # 记录每个文件读取偏移量
        self.file_read_pos = {k: 0 for k in LOG_FILE_MAP.keys()}
        self.running_flag = True

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

        # 下层单区
        f5 = tk.Frame(self.main_pane, bg=BG_COLOR, bd=0)
        self.main_pane.add(f5, weight=1)
        tk.Label(f5, text="强势监控区", fg=FG_COLOR, bg=BG_COLOR, font=("Consolas",TITLE_FONT_SIZE,"bold")).pack(anchor="nw", padx=2)
        self.t5 = tk.Text(f5, font=("Consolas",LOG_FONT_SIZE), bg=BG_COLOR, fg=FG_COLOR, insertbackground=CURSOR_COLOR, wrap=tk.CHAR, bd=0, relief=tk.FLAT)
        self.t5.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)
        s5 = ttk.Scrollbar(f5, command=self.t5.yview)
        s5.pack(side=tk.RIGHT, fill=tk.Y)
        self.t5.config(yscrollcommand=s5.set)

        self.bind_scroll_event()
        self.bind_drag_event()
        self.start_file_monitor_threads()

    def limit_log_lines(self, text_widget):
        line_cnt = int(text_widget.index(tk.END).split('.')[0])
        if line_cnt > MAX_LOG_LINES:
            text_widget.delete("1.0", f"{line_cnt - MAX_LOG_LINES}.0")

    def bind_scroll_event(self):
        text_list = [self.t1, self.t2, self.t3, self.t4, self.t5]
        def scroll_trigger(event):
            self.manual_view = True
            self.last_scroll_time = time.time()
        for txt in text_list:
            txt.bind("<MouseWheel>", scroll_trigger)

    def safe_append_log(self, text_widget, msg):
        def inner():
            t_str = time.strftime("%H:%M:%S")
            text_widget.insert(tk.END, f"[{t_str}] {msg}\n")
            self.limit_log_lines(text_widget)
            if self.manual_view and (time.time() - self.last_scroll_time) > RESUME_FOLLOW_DELAY:
                self.manual_view = False
            if not self.manual_view:
                text_widget.see(tk.END)
        self.root.after_idle(inner)

    def bind_drag_event(self):
        def drag_start(_):
            self.t1.config(state=tk.DISABLED)
            self.t2.config(state=tk.DISABLED)
            self.t3.config(state=tk.DISABLED)
            self.t4.config(state=tk.DISABLED)
            self.t5.config(state=tk.DISABLED)
        def drag_end(_):
            self.t1.config(state=tk.NORMAL)
            self.t2.config(state=tk.NORMAL)
            self.t3.config(state=tk.NORMAL)
            self.t4.config(state=tk.NORMAL)
            self.t5.config(state=tk.NORMAL)

        self.top_pane.bind("<ButtonPress-1>", drag_start)
        self.top_pane.bind("<ButtonRelease-1>", drag_end)
        self.mid_pane.bind("<ButtonPress-1>", drag_start)
        self.mid_pane.bind("<ButtonRelease-1>", drag_end)
        self.main_pane.bind("<ButtonPress-1>", drag_start)
        self.main_pane.bind("<ButtonRelease-1>", drag_end)

    # 原有对外接口不变
    def log_warn(self, msg):
        self.safe_append_log(self.t1, msg)
    def log_strong(self, msg):
        self.safe_append_log(self.t2, msg)
    def log_market(self, msg):
        self.safe_append_log(self.t3, msg)
    def log_position(self, msg):
        self.safe_append_log(self.t4, msg)
    def log_system(self, msg):
        self.safe_append_log(self.t5, msg)

    def get_text_widget(self, widget_key):
        widget_map = {
            "t1": self.t1,
            "t2": self.t2,
            "t3": self.t3,
            "t4": self.t4,
            "t5": self.t5
        }
        return widget_map.get(widget_key)

    def single_file_monitor(self, widget_key, file_path):
        pos = self.file_read_pos[widget_key]
        txt_widget = self.get_text_widget(widget_key)

        while self.running_flag:
            try:
                if not os.path.exists(file_path):
                    time.sleep(LOG_POLL_INTERVAL)
                    continue
                # UTF-8 读取
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    new_lines = f.readlines()
                    pos = f.tell()
                    self.file_read_pos[widget_key] = pos
                if new_lines:
                    content = "".join(new_lines)
                    def update_ui():
                        txt_widget.insert(tk.END, content)
                        self.limit_log_lines(txt_widget)
                        if self.manual_view and (time.time() - self.last_scroll_time) > RESUME_FOLLOW_DELAY:
                            self.manual_view = False
                        if not self.manual_view:
                            txt_widget.see(tk.END)
                    self.root.after_idle(update_ui)
            except Exception:
                pass
            time.sleep(LOG_POLL_INTERVAL)

    def start_file_monitor_threads(self):
        for key, full_path in LOG_FILE_MAP.items():
            t = threading.Thread(target=self.single_file_monitor, args=(key, full_path), daemon=True)
            t.start()

    def close_all_monitor(self):
        self.running_flag = False

# 测试打印线程
def test_loop(app):
    while True:
        app.log_warn("高位个股冲高回落，资金出逃迹象明显")
        app.log_strong("题材龙头放量拉升，做多情绪升温")
        app.log_market("大盘指数震荡整理，板块轮动节奏平稳")
        app.log_position("持仓标的进入观察区间，等待方向确认")
        app.log_system("行情数据采集正常，后台服务运行稳定")
        time.sleep(0.8)

if __name__ == "__main__":
    root = tk.Tk()
    log_ui = QuantLogPanel(root)

    def on_close():
        log_ui.close_all_monitor()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    # 如需只监控文件，注释下面这行即可
    #threading.Thread(target=test_loop, args=(log_ui,), daemon=True).start()
    root.mainloop()