# ==============================================
# MiniQMT 龙头股量化策略（高并发完整版+订单流五大指标）
# 核心特性：
# 1. 轻量化Tick回调，仅存储原始行情，无复杂计算，不丢Tick
# 2. 双独立线程池：DDX/DDZ计算池、订单流指标计算池，资源隔离
# 3. 独立守护线程每3分钟计算当期TOP5龙头【前5分钟区间订单流】
# 4. 五大订单流识别：撤单诱多诱空、对倒虚假放量、拆单隐形主力、盘口承接失衡、主动资金方向
# 5. 综合得分 = 原生龙头分(0~100) + 订单流分(0~50)，区分真假主力骗线
# 6. 多后台常驻线程：板块刷新、强势股监控、订单流分析、主选股循环解耦
# 7. 滚动队列管控内存、读写短锁多线程安全、9:45延迟选股、日线本地缓存加速
# ==============================================
import sys
import subprocess
import time
import math
import json
import os
import re
import threading
import asyncio
from typing import Dict
# 线程池：并行计算隔离任务
from concurrent.futures import ThreadPoolExecutor, wait
# 容器：滚动缓存队列、多层字典
from collections import defaultdict, deque
# 类型注解规范代码
from typing import Dict, List, Tuple, Optional
# 时间处理：交易窗口、3分钟区间、日期下载区间
from datetime import datetime, timedelta

# MiniQMT官方交易&行情API
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
from xtquant import xtdata

# =============================================================================
#                                   全局变量
# =============================================================================
cond1_stocks_value = 35      #条件1:5日涨幅 > cond1_stocks_value%
cond2_stocks_value = 45      #条件2:5日涨幅 > cond2_stocks_value%

# =============================================================================
# 模块1：日线历史数据缓存下载（避免重复下载，提速启动）
# =============================================================================
# 缓存文件本地路径
CACHE_FILE = r"C:\Users\15113\Desktop\QMT_Software\py\downloaded_stocks.json"
# 集合存储已下载股票，查询O(1)速度
DOWNLOADED_STOCKS = set()

# 读取本地缓存文件
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            DOWNLOADED_STOCKS = set(json.load(f))
        print(f"✅ 加载日线缓存：{len(DOWNLOADED_STOCKS)} 只股票无需重复下载")
    except Exception:
        DOWNLOADED_STOCKS = set()

def save_download_cache():
    """持久化保存已下载股票列表到本地JSON"""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(list(DOWNLOADED_STOCKS), f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def is_downloaded(code):
    """判断单只股票是否已缓存日线"""
    return code in DOWNLOADED_STOCKS

def mark_downloaded(code):
    """标记股票为已下载，同步更新本地缓存"""
    DOWNLOADED_STOCKS.add(code)
    save_download_cache()

def batch_download_history(stock_list, days=10):
    """批量下载日线，自动过滤已缓存标的"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    # 筛选未下载股票
    need_list = [s for s in stock_list if not is_downloaded(s)]
    total = len(need_list)
    print(f"✅ 待下载日线股票总数：{total}")
    count = 0
    for code in need_list:
        try:
            xtdata.download_history_data(code, "1d", start, end)
            mark_downloaded(code)
            count += 1
            time.sleep(0.05)
        except Exception:
            continue
        # 每50只打印下载进度
        if count % 50 == 0:
            print(f"日线下载进度：{count}/{total}")
            time.sleep(0.5)
    print(f"✅ 日线批量下载完成，新增{count}只，缓存合计{len(DOWNLOADED_STOCKS)}只")

# 统一判断A股正常交易时段
def is_trade_time(h, m):

# 早盘 09:30-11:30
    if 9 < h < 11:
        return True
    if h == 9 and m >= 30:
        return True
    if h == 11 and m <= 30:
        return True
    # 午盘 13:00-15:00
    if 13 <= h < 15:
        return True
    if h == 15 and m == 0:
        return True
    return False
# 统一判断A股正常交易时段
def is_trade_time2(h, m):
# 早盘 09:30-11:30
    if 9 < h < 11:
        return True
    if h == 9 and m >= 30:
        return True
    if h == 9 and m <= 59:
        return True
    
    return False

def is_trade_time3(h, m):
# 早盘 09:30-9:46
    if h == 9 and m >= 30 and m <= 46:
        return True 
    return False
# =============================================================================
# 模块2：全局单例行情数据中心（统一缓存所有Tick/逐笔/委托/计算结果）
# 设计：单例全局唯一、可重入读写锁、滚动队列控内存、读写分离
# =============================================================================
class StockDataCenter:
    # 单例静态实例
    _instance = None
    # 单例创建互斥锁
    _instance_lock = threading.Lock()

    def __new__(cls):
        """线程安全单例构造，全局仅一份缓存"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init_data_structures()
        return cls._instance

    def _init_data_structures(self):
        # -------------------------- 内存管控参数 --------------------------
        self.MAX_TICK_CACHE = 200          # 单股票Tick最大缓存条数
        self.MAX_TRANSACTION_CACHE = 12000  # 单股票逐笔成交上限
        self.MAX_ORDER_CACHE = 20000        # 单股票逐笔委托上限，覆盖完整3分钟行情
        self.BIG_ORDER_THRESHOLD = 200000  # 20万元=大单判定阈值
        self.DDX_WORKERS = 8               # DDX/DDZ计算线程池并发数
        self.ORDERFLOW_WORKERS = 4         # 订单流指标计算线程池并发数

        self._data_lock = threading.RLock() # 可重入读写锁，防止同线程死锁

        # -------------------------- 基础Tick行情缓存 --------------------------
        self.stock_tick_cache: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.MAX_TICK_CACHE))
        self.stock_latest_tick: Dict[str, dict] = {} # 每只股票最新完整Tick快照
        self.stock_hot_concept: Dict[str, Tuple[str, float]] = {} # 股票-最强题材映射
        self.sector_float_mv: Dict[str, Dict[str, float]] = defaultdict(dict) # 板块内个股流通市值
        self.timestamps: Dict[str, datetime] = {"tick": datetime.min}

        # -------------------------- DDX/DDZ 逐笔成交缓存 --------------------------
        self.stock_transaction_cache: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.MAX_TRANSACTION_CACHE))
        self.stock_ddx_ddz: Dict[str, Tuple[float, float]] = {} # 存储当日累计DDX、DDZ
        self.stock_ddx_ddz_prev: Dict[str, Tuple[float, float]] = {}
        self.executor = ThreadPoolExecutor(max_workers=self.DDX_WORKERS, thread_name_prefix="DDX_CALC")

        # -------------------------- 订单流分析专用缓存 --------------------------
        self.stock_order_cache: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.MAX_ORDER_CACHE)) # 逐笔委托/撤单
        self.stock_orderflow_score: Dict[str, dict] = defaultdict(dict) # 订单流分项得分+总分
        self.orderflow_executor = ThreadPoolExecutor(max_workers=self.ORDERFLOW_WORKERS, thread_name_prefix="ORDERFLOW")

    # -------------------------- 写入接口（Tick回调专用，无任何计算） --------------------------
    def update_stock_transaction(self, stock_code: str, transaction_data: dict):
        """写入单条逐笔成交，仅追加缓存"""
        with self._data_lock:
            self.stock_transaction_cache[stock_code].append(transaction_data)

    def update_stock_order(self, stock_code: str, order_data: dict):
        """写入单条逐笔委托/撤单，订单流原始数据源"""
        with self._data_lock:
            self.stock_order_cache[stock_code].append(order_data)

    def update_stock_tick(self, stock_code: str, tick_data: dict):
        """更新股票最新Tick快照与历史滚动队列"""
        with self._data_lock:
            self.stock_tick_cache[stock_code].append(tick_data)
            self.stock_latest_tick[stock_code] = tick_data
            self.timestamps["tick"] = datetime.now()

    # -------------------------- DDX/DDZ 异步计算接口 --------------------------
    def async_calculate_ddx_ddz(self, stock_code: str):
        """提交DDX计算任务至线程池，回调立刻返回不阻塞行情"""
        self.executor.submit(self._sync_calculate_ddx_ddz, stock_code)

    def _sync_calculate_ddx_ddz(self, stock_code: str):
        """DDX/DDZ同步计算逻辑，后台线程执行"""
        try:
            # 短锁拷贝数据，立刻释放锁，不长期占用读写锁
            with self._data_lock:
                transactions = list(self.stock_transaction_cache.get(stock_code, []))
                latest_tick = self.stock_latest_tick.get(stock_code, {})
            if not transactions:
                return
            # 资金统计变量初始化
            big_buy_amount = 0.0
            big_sell_amount = 0.0
            big_buy_count = 0
            big_sell_count = 0
            total_amount = 0.0
            total_count = len(transactions)
            # 遍历全部逐笔统计大单资金
            for trans in transactions:
                price = trans.get("price", 0.0)
                volume = trans.get("volume", 0)
                bs_flag = trans.get("bs_flag", "")
                if price <= 0 or volume <= 0:
                    continue
                amount = price * volume / 100
                total_amount += amount
                # 区分大单买卖方向累加
                if amount >= self.BIG_ORDER_THRESHOLD:
                    if bs_flag == "B":
                        big_buy_amount += amount
                        big_buy_count += 1
                    elif bs_flag == "S":
                        big_sell_amount += amount
                        big_sell_count += 1
            # 计算DDX大单动向
            ddx = (big_buy_amount - big_sell_amount) / total_amount if total_amount > 0 else 0.0
            ddx = round(ddx, 4)
            # 提取现价、昨收，修正DDZ
            pre_close = latest_tick.get("lastClose", 0.0)
            last_price = latest_tick.get("lastPrice", 0.0)
            rise_rate = (last_price - pre_close) / pre_close * 100 if pre_close > 0 else 0.0
            ddz_base = (big_buy_count - big_sell_count) / total_count * 100 if total_count > 0 else 0.0
            ddz = round(ddz_base + rise_rate, 2)
            # 写入计算结果，绑定至Tick快照
            with self._data_lock:
                self.stock_ddx_ddz[stock_code] = (ddx, ddz)
                self.stock_latest_tick[stock_code]["DDX"] = ddx
                self.stock_latest_tick[stock_code]["DDZ"] = ddz
        except Exception:
            pass

    # -------------------------- 订单流数据读写接口 --------------------------
    def get_range_trans_and_order(self, stock_code: str, delta_seconds=300):
        """截取近N秒（默认5分钟）逐笔成交、委托副本，释放锁后再过滤时间"""
        cutoff = datetime.now() - timedelta(seconds=delta_seconds)
        trans_list = []
        order_list = []
        # 一次性拷贝全量缓存，短锁不阻塞写入
        with self._data_lock:
            all_trans = list(self.stock_transaction_cache[stock_code])
            all_order = list(self.stock_order_cache[stock_code])
        # 过滤3分钟内有效逐笔成交
        for t in all_trans:
            ts_int = t.get("time", 0)
            if ts_int <= 0:
                continue
            dt = datetime.strptime(str(ts_int)[:14], "%Y%m%d%H%M%S")
            if dt >= cutoff:
                trans_list.append(t)
        # 过滤3分钟内有效逐笔委托/撤单
        for o in all_order:
            ts_int = o.get("time", 0)
            if ts_int <= 0:
                continue
            dt = datetime.strptime(str(ts_int)[:14], "%Y%m%d%H%M%S")
            if dt >= cutoff:
                order_list.append(o)
        return trans_list, order_list

    def set_orderflow_result(self, stock_code: str, res_dict: dict):
        """保存单只股票完整订单流指标结果"""
        with self._data_lock:
            self.stock_orderflow_score[stock_code] = res_dict

    def get_orderflow_result(self, stock_code: str) -> dict:
        """读取股票最新订单流指标，无数据返回零值默认字典"""
        with self._data_lock:
            return self.stock_orderflow_score.get(stock_code, {
                "score": 0, "cancel_rate": 0, "cross_trade_ratio": 0,
                "split_order_ratio": 0, "book_imbalance": 0, "active_buy_net": 0,
                "sub_score": [0,0,0,0,0]
            })

    # -------------------------- 通用行情读取对外接口 --------------------------
    def get_ddx_ddz(self, stock_code: str) -> Tuple[float, float]:
        """获取股票累计DDX、DDZ"""
        with self._data_lock:
            return self.stock_ddx_ddz.get(stock_code, (0.0, 0.0))

    def get_latest_tick(self, stock_code: str) -> Optional[dict]:
        """获取最新完整Tick快照"""
        with self._data_lock:
            return self.stock_latest_tick.get(stock_code)

    def get_tick_history(self, stock_code: str) -> List[dict]:
        """获取股票滚动缓存内全部历史Tick"""
        with self._data_lock:
            return list(self.stock_tick_cache.get(stock_code, deque()))

    def update_stock_hot_concept(self, stock_code: str, concept_name: str, concept_rise: float):
        """更新个股最强题材与题材涨幅"""
        with self._data_lock:
            self.stock_hot_concept[stock_code] = (concept_name, concept_rise)

    def get_stock_hot_concept(self, stock_code: str) -> Optional[Tuple[str, float]]:
        """读取个股最热题材"""
        with self._data_lock:
            return self.stock_hot_concept.get(stock_code)

    def update_sector_float_mv(self, sector_name: str, stock_code: str, float_mv: float):
        """缓存板块内个股流通市值，用于板块加权涨幅计算"""
        with self._data_lock:
            self.sector_float_mv[sector_name][stock_code] = float_mv

    def get_sector_float_mv(self, sector_name: str) -> Dict[str, float]:
        """读取板块全部个股流通市值"""
        with self._data_lock:
            return dict(self.sector_float_mv.get(sector_name, {}))

    def wait_all_tasks(self):
        """选股前等待所有未完成DDX计算，保证指标完整"""
        with self._data_lock:
            stock_list = list(self.stock_latest_tick.keys())
            calculated = set(self.stock_ddx_ddz.keys())
        futures = []
        for stock in stock_list:
            if stock not in calculated:
                futures.append(self.executor.submit(self._sync_calculate_ddx_ddz, stock))
        if futures:
            wait(futures)

    def shutdown(self):
        """程序退出优雅关闭双线程池，释放资源"""
        try:
            self.executor.shutdown(wait=False)
            self.orderflow_executor.shutdown(wait=False)
        except Exception:
            pass

# 全局唯一数据中心单例实例，全程序统一调用
data_center = StockDataCenter()

# =============================================================================
# 模块3：Tick行情全推回调函数（行情入口，极致轻量化，仅存储无计算）
# MiniQMT每推送一次实时Tick自动执行本函数
# =============================================================================
def tick_callback_func(data: dict):
    """
    Tick全推回调入口
    :param data: {股票代码: Tick完整字典} 单次推送多只股票行情
    """
    try:
        # ========== 新增行情监控统计 ==========
        now = datetime.now()
        TICK_MONITOR["last_tick_recv_time"] = now
        TICK_MONITOR["total_tick_count"] += 1
        # 记录当前分钟数据包数量
        TICK_MONITOR["last_minute_tick"].append(now)
        # ======================================

        for stock_code, tick_data in data.items():
            tick_data["update_time"] = datetime.now()
            # 1. 存储Level2逐笔成交（DDX、主动单指标数据源）
            for trans in tick_data.get("transaction_data", []):
                trans_std = {
                    "price": trans.get("price", 0.0),
                    "volume": trans.get("volume", 0),
                    "bs_flag": trans.get("bs_flag", ""),
                    "time": trans.get("time", 0)
                }
                data_center.update_stock_transaction(stock_code, trans_std)
            # 2. 存储Level2逐笔委托/撤单（订单流五大指标数据源）
            for order in tick_data.get("order_data", []):
                order_std = {
                    "price": order.get("price", 0.0),
                    "volume": order.get("volume", 0),
                    "order_type": order.get("order_type", ""), # B买 S卖 C撤单
                    "order_id": order.get("order_id", ""),
                    "time": order.get("time", 0)
                }
                data_center.update_stock_order(stock_code, order_std)
            # 3. 更新Tick缓存
            data_center.update_stock_tick(stock_code, tick_data)
            # 4. 异步提交DDX计算，主线程立刻返回，不阻塞行情接收
            data_center.async_calculate_ddx_ddz(stock_code)
    except Exception:
        # 单条Tick异常静默捕获，不中断全市场行情接收
        pass

# =============================================================================
# 模块4：订单流五大指标计算核心函数（单股票3分钟区间统计打分）
# 五项指标每项0~10分，合计订单流总分0~50
# =============================================================================
def calc_single_stock_orderflow(stock_code: str):
    """计算单只龙头近3分钟完整订单流指标与分项得分"""
    trans_list, order_list = data_center.get_range_trans_and_order(stock_code, delta_seconds=180)
    # 无行情数据直接返回零值结果
    if not trans_list and not order_list:
        empty_res = {
            "score": 0, "cancel_rate": 0, "cross_trade_ratio": 0,
            "split_order_ratio": 0, "book_imbalance": 0, "active_buy_net": 0,
            "sub_score": [0,0,0,0,0]
        }
        data_center.set_orderflow_result(stock_code, empty_res)
        return empty_res

    # 指标1：高频撤单率 S1（识别诱多诱空，撤单越高分越低）
    total_order_vol = 0
    cancel_vol = 0
    for o in order_list:
        vol = o["volume"]
        total_order_vol += vol
        if o["order_type"] == "C":
            cancel_vol += vol
    cancel_rate = cancel_vol / total_order_vol if total_order_vol > 0 else 0
    if cancel_rate < 0.1:
        s1 = 10
    elif cancel_rate < 0.2:
        s1 = 6
    elif cancel_rate < 0.3:
        s1 = 3
    else:
        s1 = 0

    # 指标2：对倒成交占比 S2（识别虚假放量，对倒越多分越低）
    cross_trade_vol = 0
    total_trans_vol = 0
    trans_copy = trans_list.copy()
    matched_ids = set()
    for idx, t in enumerate(trans_copy):
        if idx in matched_ids:
            continue
        total_trans_vol += t["volume"]
        for jdx, t2 in enumerate(trans_copy):
            if jdx in matched_ids or idx == jdx:
                continue
            if abs(t["price"] - t2["price"]) < 0.01 and t["bs_flag"] != t2["bs_flag"]:
                cross_trade_vol += min(t["volume"], t2["volume"])
                matched_ids.add(idx)
                matched_ids.add(jdx)
                break
    cross_ratio = cross_trade_vol / total_trans_vol if total_trans_vol > 0 else 0
    if cross_ratio < 0.05:
        s2 = 10
    elif cross_ratio < 0.15:
        s2 = 6
    elif cross_ratio < 0.25:
        s2 = 3
    else:
        s2 = 0

    # 指标3：拆单占比 S3（识别隐形主力吸筹/出货，拆单越多加分越高）
    split_vol = 0
    small_single_threshold = 50 * 100 # 50手以下判定为拆单
    for t in trans_list:
        if t["volume"] < small_single_threshold:
            split_vol += t["volume"]
    split_ratio = split_vol / total_trans_vol if total_trans_vol > 0 else 0
    if split_ratio > 0.4:
        s3 = 10
    elif split_ratio > 0.25:
        s3 = 7
    elif split_ratio > 0.1:
        s3 = 4
    else:
        s3 = 1

    # 指标4：盘口失衡度 S4（识别真实承接/抛压，买盘越强分越高）
    bid_vol = 0
    ask_vol = 0
    for o in order_list:
        vol = o["volume"]
        if o["order_type"] == "B":
            bid_vol += vol
        elif o["order_type"] == "S":
            ask_vol += vol
    book_imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0
    if book_imbalance > 0.3:
        s4 = 10
    elif book_imbalance > 0.1:
        s4 = 7
    elif book_imbalance > -0.1:
        s4 = 4
    else:
        s4 = 0

    # 指标5：主动单净资金比例 S5（判断真实资金进攻方向）
    active_buy_amt = 0.0
    active_sell_amt = 0.0
    for t in trans_list:
        amt = t["price"] * t["volume"] / 100
        if t["bs_flag"] == "B":
            active_buy_amt += amt
        elif t["bs_flag"] == "S":
            active_sell_amt += amt
    active_net = active_buy_amt - active_sell_amt
    total_amt = active_buy_amt + active_sell_amt
    active_net_ratio = active_net / total_amt if total_amt > 0 else 0
    if active_net_ratio > 0.2:
        s5 = 10
    elif active_net_ratio > 0.05:
        s5 = 7
    elif active_net_ratio > -0.05:
        s5 = 4
    else:
        s5 = 0

    # 五项求和得到订单流综合总分0~50
    orderflow_total = s1 + s2 + s3 + s4 + s5
    res = {
        "score": orderflow_total,
        "cancel_rate": round(cancel_rate, 3),
        "cross_trade_ratio": round(cross_ratio, 3),
        "split_order_ratio": round(split_ratio, 3),
        "book_imbalance": round(book_imbalance, 3),
        "active_buy_net": round(active_net_ratio, 3),
        "sub_score": [s1, s2, s3, s4, s5]
    }
    data_center.set_orderflow_result(stock_code, res)
    return res

# =============================================================================
# 模块5：订单流独立后台守护线程（每3分钟一轮计算当期TOP5）
# =============================================================================
def orderflow_analysis_thread(top5_queue: deque, is_running: list):
    """订单流常驻后台线程，不占用主线程资源"""
    print("✅ 订单流分析守护线程启动，每3分钟计算一轮TOP5龙头5分钟区间订单流")
    while is_running[0]:
        # 上报心跳
        THREAD_HEARTBEAT["orderflow_analysis"] = datetime.now()
        target_codes = list(set(top5_queue))
        if target_codes:
            futures = []
            for code in target_codes:
                fut = data_center.orderflow_executor.submit(calc_single_stock_orderflow, code)
                futures.append(fut)
            for f in futures:
                try:
                    f.result(timeout=10)
                except Exception:
                    continue
        # 循环休眠180秒，每秒检测退出标志，支持快速退出
        for _ in range(180):
            if not is_running[0]:
                return
            time.sleep(1)

# =============================================================================
# 模块6：龙头选股核心打分、六大龙头规则、选股筛选工具函数
# =============================================================================
def get_6_rules(stock, sector, close, rise, amt, ddz):
    """统计六大龙头规则满足条数（0~6）"""
    s5_rise = (close[-1] / close[-5] - 1) * 100
    r1 = rule1_time_lead(stock, sector)
    r2 = rule2_beta(sector, s5_rise, rise)
    r3 = rule3_sector_sync(sector)
    r4 = rule4_funding(sector, amt, ddz)
    r5 = rule5_trend(sector, s5_rise)
    r6 = rule6_not_fake(sector, rise)
    return sum([r1, r2, r3, r4, r5, r6])

def score(stock, sector, close, rise, amt, ddz, ddx):
    """原生龙头综合打分0~100分，基于资金、趋势、板块、六大规则加权"""
    score_val = 0
    s5_rise = (close[-1] / close[-5] - 1) * 100
    # DDX大单资金加分
    if ddx > 0.5:
        score_val += 15
    elif ddx > 0.2:
        score_val += 10
    # DDZ大单持续进攻加分
    if ddz > 30:
        score_val += 15
    elif ddz > 20:
        score_val += 10
    # 板块成交额核心标的加分
    try:
        if amt / G_SECTOR_TOTAL_AMT[sector] >= 0.06:
            score_val += 5
    except Exception:
        pass
    # 5日强趋势加分
    if s5_rise > 15:
        score_val += 5
    # 板块下跌个股逆势上涨加分
    try:
        t, _, p = G_SECTOR_PRICE[sector]
        if t > 0 and p > 0:
            sp = (t / p - 1) * 100
            if sp < 0 and rise > 4:
                score_val += 5
    except Exception:
        pass
    # 时间/强度领先单项加分
    if rule2_beta(sector, s5_rise, rise):
        score_val += 10
    if rule1_time_lead(stock, sector):
        score_val += 10
    # 六大规则核心权重加分
    rule_cnt = get_6_rules(stock, sector, close, rise, amt, ddz)
    if rule_cnt == 6:
        score_val += 35
    elif rule_cnt == 5:
        score_val += 30
    elif rule_cnt == 4:
        score_val += 25
    elif rule_cnt == 3:
        score_val += 20
    return min(score_val, 100)

def filter_stock_by_rules(pool):
    """第一轮粗筛：仅保留至少满足3条龙头规则的标的"""
    score_pool = []
    for stock in pool:
        sec = G_SECTOR_MAP.get(stock)
        if not sec:
            continue
        try:
            day_data = xtdata.get_local_data(stock, "1d", count=50)
            if len(day_data["close"]) < 5:
                continue
            close_arr = day_data["close"]
            pre_close = day_data["preClose"][-1]
            now_p = get_now_price(stock)
            rise = (now_p / pre_close - 1) * 100
            amt = xtdata.get_field(stock, "amount")
            # 单日成交额低于10亿过滤
            if amt < 1000000000:
                continue
            code_prefix = stock.split(".")[0]
            # 主板日内涨幅区间过滤
            if code_prefix[:2] in ["60", "00"] and not (3 <= rise <= 9.8):
                continue
            # 创科板日内涨幅区间过滤
            if code_prefix[:3] in ["300", "301", "688"] and not (4 <= rise <= 14.8):
                continue
            ddx, ddz = data_center.get_ddx_ddz(stock)
            rule_count = get_6_rules(stock, sec, close_arr, rise, amt, ddz)
            if rule_count >= 3:
                score_pool.append(stock)
        except Exception:
            continue
    return score_pool

def score_stocks(score_pool):
    """第二轮精细打分：对粗筛候选池计算原生龙头得分"""
    final_score_map = {}
    for stock in score_pool:
        try:
            sec = G_SECTOR_MAP[stock]
            day_data = xtdata.get_local_data(stock, "1d", count=50)
            close_arr = day_data["close"]
            pre_close = day_data["preClose"][-1]
            now_p = get_now_price(stock)
            rise = (now_p / pre_close - 1) * 100
            amt = xtdata.get_field(stock, "amount")
            ddx, ddz = data_center.get_ddx_ddz(stock)
            final_score_map[stock] = score(stock, sec, close_arr, rise, amt, ddz, ddx)
        except Exception:
            continue
    return final_score_map

def select_stock_once(pool, top5_queue: deque):
    """单次完整选股：粗筛→打分→TOP5入队→融合订单流总分打印榜单"""
    score_pool = filter_stock_by_rules(pool)
    if not score_pool:
        print("❌ 本轮无满足龙头基础规则股票")
        return
    final_map = score_stocks(score_pool)
    # 原生分数取前5
    raw_rank = sorted(final_map.items(), key=lambda x: x[1], reverse=True)[:5]
    raw_top5 = [code for code, _ in raw_rank]
    # TOP5送入订单流分析队列
    for c in raw_top5:
        top5_queue.append(c)
    # 融合订单流得分计算综合总分
    combine_dict = {}
    for code, stock_score in raw_rank:
        of_info = data_center.get_orderflow_result(code)
        of_score = of_info["score"]
        total = stock_score + of_score
        combine_dict[code] = {
            "stock_score": stock_score,
            "orderflow_score": of_score,
            "total_score": total,
            "of_detail": of_info
        }
    # 综合总分重新排序输出
    combine_rank = sorted(combine_dict.items(), key=lambda x: x[1]["total_score"], reverse=True)
    print("\n======= 叠加3分钟订单流综合龙头TOP5 =======")
    header = f"{'代码':<12}{'名称':<10}{'题材':<12}{'龙头分':<6}{'订单流分':<8}{'综合总分':<8}{'撤单率':<8}{'对倒占比':<8}{'拆单占比':<8}{'盘口失衡':<8}{'主动净比':<8}"
    print(header)
    print("-" * 132)
    for code, info in combine_rank:
        try:
            stock_info = xtdata.get_instrument_detail(code)
            name = stock_info.get("InstrumentName", "-")
            hot = data_center.get_stock_hot_concept(code)
            concept = hot[0] if hot else "未知"
            of = info["of_detail"]
            print(f"{code:<12}{name:<10}{concept:<12}{info['stock_score']:<6}{of['score']:<8}{info['total_score']:<8}"
                  f"{of['cancel_rate']:<8.3f}{of['cross_trade_ratio']:<8.3f}{of['split_order_ratio']:<8.3f}"
                  f"{of['book_imbalance']:<8.3f}{of['active_buy_net']:<8.3f}")
        except Exception:
            continue

# -------------------------- 六大龙头规则独立实现函数 --------------------------
def rule1_time_lead(stock, sector):
    """规则1：时间领先启动，个股先涨板块后跟风"""
    try:
        s = xtdata.get_local_data(stock, "5m", count=3)["close"]
        se = xtdata.get_local_data(sector, "5m", count=3)["close"]
        return s[2] > s[1] > s[0] and se[2] > se[1] and se[1] < se[0]
    except Exception:
        return False

def rule2_beta(sector, s5, rise):
    """规则2：强度领先，个股日内、5日涨幅大幅跑赢板块"""
    try:
        t, c5, p = G_SECTOR_PRICE[sector]
        sec5 = (t / c5 - 1) * 100
        sec2 = (t / p - 1) * 100
        return rise / sec2 >= 1.2 and s5 / sec5 >= 1.1
    except Exception:
        return False

def rule3_sector_sync(sector):
    """规则3：板块联动，板块内至少15%个股同步上涨"""
    try:
        stocks = G_SECTOR_STOCK.get(sector, [])[:25]
        cnt = 0
        for s in stocks:
            pre = xtdata.get_local_data(s, "1d", count=1)["preClose"][0]
            if (get_now_price(s) / pre - 1) * 100 >= 2:
                cnt += 1
        return cnt >= len(stocks) * 0.15
    except Exception:
        return False

def rule4_funding(sector, amt, ddz):
    """规则4：板块核心资金标的，成交额占板块6%以上且DDZ强势"""
    try:
        total = G_SECTOR_TOTAL_AMT.get(sector, 0)
        return amt / total >= 0.06 and ddz >= 20
    except Exception:
        return False

def rule5_trend(sector, s5):
    """规则5：中长期趋势大幅领先板块"""
    try:
        t, c5, _ = G_SECTOR_PRICE[sector]
        return s5 >= (t / c5 - 1) * 100 + 8
    except Exception:
        return False

def rule6_not_fake(sector, rise):
    """规则6：无假突破行情，个股与板块节奏无严重背离"""
    try:
        t, _, p = G_SECTOR_PRICE[sector]
        sec = (t / p - 1) * 100
        if (sec > 2 and rise < sec) or (rise > 5 and sec < -1.5):
            return False
        return True
    except Exception:
        return True

# =============================================================================
# 模块7：板块解析、行情订阅、基础过滤、通用工具函数
# =============================================================================
def parse_tdx_sector_data(dat_path):
    """解析通达信本地板块文件，生成股票-板块、板块-指数映射"""
    stock_map = {}
    sector_index_map = {}
    current_sector = None
    with open(dat_path, "r", encoding="gbk", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                parts = line.split(",")
                current_sector = parts[0].replace("#GN_", "")
                if len(parts) >= 3:
                    idx = parts[2].strip()
                    if len(idx) == 6 and idx.startswith("88"):
                        sector_index_map[current_sector] = idx + ".SH"
                continue
            if not current_sector:
                continue
            for item in line.split(","):
                item = item.strip()
                if "#" not in item:
                    continue
                code = item.split("#")[-1]
                if len(code) != 6 or not code.isdigit():
                    continue
                # 拼接市场后缀
                if code.startswith("6"):
                    code = code + ".SH"
                elif code.startswith(("4", "8")):
                    code = code + ".BJ"
                else:
                    code = code + ".SZ"
                if code not in stock_map:
                    stock_map[code] = []
                if current_sector not in stock_map[code]:
                    stock_map[code].append(current_sector)
    return stock_map, sector_index_map

def check_market_push_status(strategy_started_flag):
    """
    功能1：监测行情推送是否正常、是否限流
    返回告警文本，无异常返回空字符串
    """
    now = datetime.now()
    last_tick_time = TICK_MONITOR["last_tick_recv_time"]
    delta_sec = (now - last_tick_time).total_seconds()
    warn_msg = ""

    # 1. 长时间无Tick推送，断流告警
    if delta_sec > 10:
        warn_msg += f"【行情异常】已{int(delta_sec)}秒未收到任何Tick推送，行情断流！;"
    
    # 2. 订阅数量接近上限，限流风险告警
    sub_count = TICK_MONITOR["subscribe_total"]
    if sub_count >= TICK_MONITOR["warning_limit"]:
        TICK_MONITOR["is_flow_limited"] = True
        warn_msg += f"【限流风险】当前订阅股票{sub_count}只，接近柜台推送上限，存在限流丢包风险！;"
    else:
        TICK_MONITOR["is_flow_limited"] = False

    # 3. 统计近1分钟Tick数据包数量，流量过低提示
    one_minute_pack = len(TICK_MONITOR["last_minute_tick"])
    if strategy_started_flag and one_minute_pack < 50:
        warn_msg += f"【流量偏低】近1分钟仅收到{one_minute_pack}组Tick数据包，推送流量不足;"

    return warn_msg


def check_all_thread_health():
    """
    功能2：监测所有后台线程是否卡死、停止运行
    返回线程异常告警文本，无异常返回空
    """
    now = datetime.now()
    warn_msg = ""
    thread_name_map = {
        "sector_refresh": "板块刷新线程",
        "orderflow_analysis": "订单流分析线程",
        "strong_monitor": "强势股监控线程",
        "main_strategy": "主选股线程"
    }
    for key, name in thread_name_map.items():
        last_hb = THREAD_HEARTBEAT[key]
        gap = (now - last_hb).total_seconds()
        if gap > THREAD_TIMEOUT_SEC:
            warn_msg += f"【线程卡死】{name} 已{int(gap)}秒无心跳，线程停止工作！;"
    return warn_msg


def print_full_monitor_report(strategy_started_flag):
    """每30秒打印一次完整监控健康报告"""
    global last_monitor_print
    now = datetime.now()
    if (now - last_monitor_print).total_seconds() < MONITOR_PRINT_INTERVAL:
        return
    last_monitor_print = now

    print("\n==================== 系统健康监控报告 ====================")
    # 1. 行情推送状态
    market_warn = check_market_push_status(strategy_started_flag)
    print(f"【行情推送监测】")
    print(f"  累计接收Tick数据包总数：{TICK_MONITOR['total_tick_count']}")
    print(f"  最后一次收到Tick时间：{TICK_MONITOR['last_tick_recv_time'].strftime('%H:%M:%S')}")
    print(f"  当前订阅股票数量：{TICK_MONITOR['subscribe_total']}")
    print(f"  近1分钟Tick数据包数量：{len(TICK_MONITOR['last_minute_tick'])}")
    if market_warn:
        print(f"  ⚠️ 行情告警：{market_warn}")
    else:
        print(f"  ✅ 行情推送正常，无断流/限流风险")
    
    # 2. 线程健康状态
    thread_warn = check_all_thread_health()
    print(f"\n【后台线程健康监测】")
    if thread_warn:
        print(f"  ⚠️ 线程异常告警：{thread_warn}")
    else:
        print(f"  ✅ 全部线程心跳正常，无卡死")
    
    print("===========================================================\n")


def init_stock_sector_dict():
    """加载板块JSON缓存，无缓存则解析通达信文件生成并持久化"""
    global STOCK_SECTOR_DICT, SECTOR_INDEX_MAP, SECTOR_STOCK_MAP
    p = os.path.dirname(os.path.abspath(__file__))
    j1 = os.path.join(p, "stock_sector_dict.json")
    j2 = os.path.join(p, "sector_index_map.json")
    j3 = os.path.join(p, "sector_stock_map.json")
    # 股票→板块映射
    if os.path.exists(j1):
        with open(j1, "r", encoding="utf-8") as f:
            STOCK_SECTOR_DICT = json.load(f)
    else:
        STOCK_SECTOR_DICT, SECTOR_INDEX_MAP = parse_tdx_sector_data(TDX_BLOCK_FILE)
        with open(j1, "w", encoding="utf-8") as f:
            json.dump(STOCK_SECTOR_DICT, f, ensure_ascii=False)
    # 板块→指数映射
    if os.path.exists(j2):
        with open(j2, "r", encoding="utf-8") as f:
            SECTOR_INDEX_MAP = json.load(f)
    else:
        with open(j2, "w", encoding="utf-8") as f:
            json.dump(SECTOR_INDEX_MAP, f, ensure_ascii=False)
    # 板块→旗下股票映射
    if os.path.exists(j3):
        with open(j3, "r", encoding="utf-8") as f:
            SECTOR_STOCK_MAP = json.load(f)
    else:
        SECTOR_STOCK_MAP = {}
        for c, ss in STOCK_SECTOR_DICT.items():
            for s in ss:
                if s not in SECTOR_STOCK_MAP:
                    SECTOR_STOCK_MAP[s] = []
                SECTOR_STOCK_MAP[s].append(c)
        with open(j3, "w", encoding="utf-8") as f:
            json.dump(SECTOR_STOCK_MAP, f, ensure_ascii=False)
    print("✅ 板块映射缓存加载完成")

def init_subscribe(pool):
    """批量订阅股票池Tick全推行情，绑定回调函数"""
    if not pool:
        return
    stocks = list(set(pool))
    print(f"✅ 开始订阅 {len(stocks)} 只股票实时Tick行情")
    try:
        xtdata.subscribe_whole_quote(stocks, callback=tick_callback_func)
        print("✅ 行情订阅成功，Tick回调已挂载")
        # 新增：记录当前订阅数量到监控
        TICK_MONITOR["subscribe_total"] = len(stocks)
    except Exception as e:
        print(f"❌ 行情订阅失败：{e}")

def unsubscribe_all():
    """程序退出取消全部行情订阅，释放底层行情线程"""
    try:
        xtdata.unsubscribe_whole_quote()
    except Exception:
        pass

def get_now_price(stock):
    """获取实时现价：优先内存Tick缓存，兜底日线收盘价"""
    try:
        tick = xtdata.get_full_tick([stock]).get(stock, {})
        return tick.get("lastPrice", 0.0)
    except Exception:
        try:
            return xtdata.get_local_data(stock, "1d", count=1)["close"][0]
        except Exception:
            return 0.0

def basic_filter(stock):
    """基础风控过滤：剔除北交所、ST、新股、小市值"""
    try:
        code = stock.split(".")[0]
        # 过滤北交所
        if code.startswith(("4", "8")):
            return False
        info = xtdata.get_instrument_detail(stock)
        if not info:
            return False
        name = info.get("InstrumentName", "")
        # 过滤ST、退市股
        if "ST" in name or "退" in name:
            return False
        now = datetime.now()
        list_date = int(info.get("OpenDate", 0))
        # 上市不满60日新股过滤
        if int(now.strftime("%Y%m%d")) - list_date < 60:
            return False
        price = get_now_price(stock)
        float_mv = info.get("FloatVolume", 0) * price
        # 流通市值低于100亿过滤
        if float_mv <= 12000000000:
            return False
        up = info.get("UpStopPrice", 0)
        down = info.get("DownStopPrice", 0)
        return True
    except Exception:
        return False

def get_limit_up_threshold(code: str):
        """根据股票代码判断涨停幅度阈值"""
        pure_code = code.split(".")[0]
        # 科创板 688 / 创业板300、301 20%涨跌幅
        if pure_code.startswith(("688", "300", "301")):
            return 1.198
        # 主板 60、00开头 10%涨跌幅
        else:
            return 1.098

# 从文本读取三类股票代码
def load_stock_from_txt(watch_list_path):
    cond1 = []
    cond2 = []
    cond3 = []
    if not os.path.exists(watch_list_path):
        return cond1, cond2, cond3
    try:
        with open(watch_list_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        flag = ""
        for line in lines:
            if f"条件1" in line:
                flag = "cond1"
                continue
            if f"条件2" in line:
                flag = "cond2"
                continue
            if f"条件3" in line:
                flag = "cond3"
                continue
            # 提取 代码 | 名称 格式里的代码
            if "|" in line and "." in line:
                code = line.split("|")[0].strip()
                if flag == "cond1":
                    cond1.append(code)
                elif flag == "cond2":
                    cond2.append(code)
                elif flag == "cond3":
                    cond3.append(code)
    except:
        pass
    return cond1, cond2, cond3

def filter_strong_stocks_separate(pool):
    """
    分离三类强势股：
    cond1_stocks：5日涨幅>cond1_stocks_value%
    cond2_stocks：5日涨幅>cond2_stocks_value%
    cond3_stocks：满足【昨涨停、前日不涨停、流通市值500亿以上】
    筛选结果同时输出控制台 + 写入固定路径WatchList.txt
    文件路径：C:/Users/15113/Desktop/QMT_Software/py/WatchList.txt
    """
    # 使用原始字符串r"" 彻底规避路径转义问题
    watch_list_path = r"C:\Users\15113\Desktop\QMT_Software\py\A_WatchList.txt"
    SECTOR_NAME = "强势股池" 
    # ========== WatchList.txt有内容直接停止所有筛选,暂时注释，放开之后get_market_data_ex会卡住 ==========
    #if os.path.exists(watch_list_path):
    #    try:
    #        with open(watch_list_path, "r", encoding="utf-8") as f:
    #            txt_content = f.read().strip()
    #        if txt_content:
    #            print("✅ 检测到已有筛选列表，直接加载本地数据，跳过行情筛选")
    #            c1, c2, c3 = load_stock_from_txt(watch_list_path)
    #            return c1, c2, c3
    #    except:
    #        pass

    cond1_stocks = []
    cond2_stocks = []
    cond3_stocks = []

    def get_stock_name(code):
        """内部工具：统一获取股票名称，简化重复代码"""
        try:
            return xtdata.get_instrument_detail(code).get("InstrumentName", "未知")
        except Exception:
            return "名称获取失败"

    for stock in pool:
        try:
            df_dict = xtdata.get_market_data_ex(["close", "preClose"], [stock], period="1d", count=6)
            
            df = df_dict.get(stock)
            if df is None or len(df) < 6:
                continue
            close = df["close"].tolist()
            preClose = df["preClose"].tolist()
            rise5d = (close[-1] / close[-6] - 1) * 100

            if rise5d > cond2_stocks_value:
                cond2_stocks.append(stock)
            if rise5d > cond1_stocks_value:
                cond1_stocks.append(stock)

            limit_thres = get_limit_up_threshold(stock)
            limit_up_yest = close[-1] >= preClose[-1] * limit_thres
            limit_up_before = close[-2] >= preClose[-2] * limit_thres

            info = xtdata.get_instrument_detail(stock)
            price = get_now_price(stock)
            float_volume = info.get("FloatVolume", 0)
            float_mv = float_volume * price

            if limit_up_yest and not limit_up_before and float_mv > 500 * 100000000:
                cond3_stocks.append(stock)
        except Exception:
            continue

    # 控制台打印输出筛选结果
    print("\n" + "="*30)
    print(f"强势股统计:条件1={len(cond1_stocks)}只 | 条件2={len(cond2_stocks)}只 | 条件3={len(cond3_stocks)}只")
    print(f"条件1（5日涨幅>{cond1_stocks_value}%）")
    for c in cond1_stocks:
        name = get_stock_name(c)
        print(f"  {c} | {name}")

    print(f"\n条件2（5日涨幅>{cond2_stocks_value}%）")
    for c in cond2_stocks:
        name = get_stock_name(c)
        print(f"  {c} | {name}")

    print("\n条件3（昨涨停+流通市值500亿以上）")
    for c in cond3_stocks:
        name = get_stock_name(c)
        print(f"  {c} | {name}")
    print("="*30 + "\n")

    # 写入本地WatchList.txt文件
    try:
        with open(watch_list_path, "w", encoding="utf-8") as f:
            now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"===== 强势股筛选列表 | 更新时间：{now_time} =====\n")
            f.write(f"强势股统计:条件1={len(cond1_stocks)}只 | 条件2={len(cond2_stocks)}只 | 条件3={len(cond3_stocks)}只\n\n")

            f.write(f"条件1（5日涨幅>{cond1_stocks_value}%）\n")
            for c in cond1_stocks:
                name = get_stock_name(c)
                f.write(f"  {c} | {name}\n")

            f.write(f"\n条件2（5日涨幅>{cond1_stocks_value}%）\n")
            for c in cond2_stocks:
                name = get_stock_name(c)
                f.write(f"  {c} | {name}\n")

            f.write("\n条件3（昨涨停+流通市值500亿以上）\n")
            for c in cond3_stocks:
                name = get_stock_name(c)
                f.write(f"  {c} | {name}\n")

            f.write("\n" + "="*35 + "\n")
        print(f"✅ 筛选列表已写入文件：{watch_list_path}")

    except Exception as e:
        print(f"❌ 写入WatchList.txt失败，错误信息：{str(e)}")

    return cond1_stocks, cond2_stocks, cond3_stocks

def get_day_close_price(clist):
    """批量获取多只股票昨收、现价"""
    d = xtdata.get_market_data_ex(["close", "preClose"], clist, "1d", 1)
    res = {}
    for c in clist:
        df = d.get(c)
        res[c] = (df["preClose"].iloc[-1], df["close"].iloc[-1]) if df and len(df) > 0 else (0, 0)
    return res

def get_real_price_fast(pool):
    """快速批量读取价格，优先内存Tick缓存"""
    res = {}
    for c in pool:
        t = data_center.get_latest_tick(c)
        if t:
            res[c] = (t.get("lastClose", 0), t.get("lastPrice", 0))
        else:
            res[c] = get_day_close_price([c])[c]
    return res

def get_stock_float_mv(code):
    """获取单只股票实时流通市值"""
    try:
        info = xtdata.get_instrument_detail(code)
        tick = data_center.get_latest_tick(code)
        price = tick.get("lastPrice", 0) if tick else 0
        return info.get("FloatVolume", 0) * price
    except Exception:
        return 0

def refresh_sector_rise(pool):
    """刷新板块加权涨幅（流通市值加权），后台线程每10秒执行"""
    global SECTOR_RISE_CACHE
    SECTOR_RISE_CACHE = {}
    pm = get_real_price_fast(pool)
    sectors = set()
    for s in pool:
        sectors.update(STOCK_SECTOR_DICT.get(s, []))
    for sec in sectors:
        stocks = SECTOR_STOCK_MAP.get(sec, [])
        total_mv = 0
        total_weight_rise = 0
        for c in stocks:
            pre, now = pm.get(c, (0, 0))
            if pre <= 0 or now <= 0:
                continue
            r = (now - pre) / pre * 100
            mv = get_stock_float_mv(c)
            total_mv += mv
            total_weight_rise += mv * r
            data_center.update_sector_float_mv(sec, c, mv)
        SECTOR_RISE_CACHE[sec] = round(total_weight_rise / total_mv, 2) if total_mv > 0 else -999

def init_all_sector_cache(pool):
    """初始化板块缓存：个股绑定最强题材、板块日线、板块总成交额"""
    global G_INIT_FLAG, G_SECTOR_MAP, G_SECTOR_STOCK
    if G_INIT_FLAG:
        return
    G_INIT_FLAG = True
    # 匹配每只股票最热题材
    for s in pool:
        sects = STOCK_SECTOR_DICT.get(s, [])
        valid = []
        for sec in sects:
            if any(k in sec for k in BLACK_LIST):
                continue
            r = SECTOR_RISE_CACHE.get(sec, -999)
            if r != -999:
                valid.append((sec, r))
        if valid:
            valid.sort(key=lambda x: x[1], reverse=True)
            best_sec = valid[0][0]
            G_SECTOR_MAP[s] = best_sec
            data_center.update_stock_hot_concept(s, best_sec, valid[0][1])
            if best_sec not in G_SECTOR_STOCK:
                G_SECTOR_STOCK[best_sec] = []
            G_SECTOR_STOCK[best_sec].append(s)
    # 预加载板块5日K线
    for sec in G_SECTOR_STOCK:
        try:
            c = xtdata.get_local_data(sec, "1d", 5)["close"]
            G_SECTOR_PRICE[sec] = (c[-1], c[-5], c[-2]) if len(c) >= 5 else (0, 0, 0)
        except Exception:
            G_SECTOR_PRICE[sec] = (0, 0, 0)
    # 预计算板块总成交额（取板块前30只活跃股）
    for sec, ss in G_SECTOR_STOCK.items():
        total = 0
        for s in ss[:30]:
            try:
                total += xtdata.get_field(s, "amount")
            except Exception:
                continue
        G_SECTOR_TOTAL_AMT[sec] = total

# =============================================================================
# 模块8：后台常驻守护线程（板块刷新、强势股监控、主选股循环）
# =============================================================================
def sector_refresh_thread(pool, is_running):
    """后台线程：每10秒刷新板块加权涨幅与题材映射"""
    while is_running[0]:
        try:
            # 上报心跳
            THREAD_HEARTBEAT["sector_refresh"] = datetime.now()
            refresh_sector_rise(pool)
            init_all_sector_cache(pool)
        except Exception:
            pass
        # 10秒一轮，每秒检测退出标志
        for _ in range(10):
            if not is_running[0]:
                return
            time.sleep(1)

# -------------------------- 行情公共解析工具函数（消除重复代码） --------------------------
def parse_tick_info(code: str):
    """
    通用tick行情解析函数，统一提取所有监控需要的基础数据
    :param code: 股票代码
    :return: 成功返回字典行情数据，字段不全返回None
    """
    tick_dict = xtdata.get_full_tick([code]).get(code, {})
    # 基础行情字段校验，任意价格为空直接丢弃该笔tick
    last_price = tick_dict.get("lastPrice", 0.0)
    open_price = tick_dict.get("open", 0.0)
    pre_close = tick_dict.get("lastClose", 0.0)
    high_price = tick_dict.get("high", 0.0)
    low_price = tick_dict.get("low", 0.0)
    time_tag = tick_dict.get("timetag", "")
    amount = tick_dict.get("amount", 0.0)

    if last_price <= 0 or open_price <= 0 or pre_close <= 0 or high_price <= 0 or low_price <= 0 or len(time_tag) < 16:
        return None

    # 拆分时间字符串 "20260615 09:32:15"
    date_str, hms_str = time_tag.split(" ")
    hour, minute, sec = map(int, hms_str.split(":"))
    # 计算核心比例数据
    open_pct = (open_price / pre_close - 1) * 100          # 开盘涨跌幅
    day_pct = (last_price / pre_close - 1) * 100           # 【新增】当前日内实时涨幅
    current_drawdown = (last_price - high_price) / high_price * 100  # 当前相对日内高点回撤幅度
    stock_name = xtdata.get_instrument_detail(code).get("InstrumentName", "未知个股")

    return {
        "code": code,
        "name": stock_name,
        "now": last_price,
        "open": open_price,
        "pre_close": pre_close,
        "high": high_price,
        "low": low_price,
        "hour": hour,
        "minute": minute,
        "open_pct": open_pct,
        "day_pct": day_pct,        # 日内实时涨幅
        "drawdown": current_drawdown,
        "time_date": date_str,
        "amount": amount           # 新增成交额字段
    }

def strong_stock_pullback_strategy(cond1_stocks, cond2_stocks, cond3_stocks, is_running):
    """
    后台独立监控线程：强势股日内回撤/横盘信号监控
    日志仅写入本地Log_StrongStock.txt，控制台无输出，状态变化才记录日志，避免刷屏
    股票分组定义：
        cond1_stocks：近5日涨幅>cond1_stocks_value% 强势个股池
        cond2_stocks：近5日涨幅>cond2_stocks_value% 核心龙头个股池
        cond3_stocks：首板涨停+市值500亿以上大盘股池
    监控规则分三大模块：
    1. cond1双分支深度回撤告警（回撤幅度>6%触发）
        分支1：开盘区间-2%~+7%，开盘后冲高超开盘5%、前10分钟最低价未跌破开盘，9:40之后检测回撤
        分支2：开盘区间-2%~+9.8%，个股在cond1，不在cond3池，仅9:30-9:40前10分钟检测回撤
    2. cond2龙头横盘告警：日内涨跌幅维持-2%~+2%，状态变化记录, 暂时屏蔽
    3. cond3涨停大盘股高开跳水告警：开盘6%~10%，仅9:30-9:40前10分钟回撤>6%触发
    日志新增：每条信号附带当前日内实时涨幅
    """
    # -------------------------- 1. 初始化日志文件 --------------------------
    # 日志文件路径：当前脚本同级目录Log_StrongStock.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(current_dir, "Log_StrongStock.txt")
    log_file = open(log_path, "a", encoding="utf-8")

    # 全局状态缓存字典：{状态唯一标识: 当前触发布尔值}，仅状态变更打印日志
    last_status = {}
    # 开盘前10分钟阶段最低价缓存：{股票代码: 09:30-09:40内最低成交价}，每日自动重置
    stock_10min_low = {}
    # 每日日期标记，用于次日清空10分钟低价缓存，避免跨日数据污染
    cache_date = datetime.now().strftime("%Y%m%d")

    # -------------------------- 2. 日志写入函数（仅写文件，不输出终端） --------------------------
    def write_log(msg):
        try:
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            content_line = f"[{time_str}] {msg}\n"  # 每条日志空一行分隔，阅读更清晰
            log_file.write(content_line)
            log_file.flush()  # 强制刷盘，实时写入文件无延迟
        except Exception:
            pass

    # 写入线程启动标识日志
    write_log("==================== 强势股监控线程启动 ====================")
    print("========== 强势股监控线程启动 ==========")
    # -------------------------- 3. 主线监控循环 --------------------------
    while is_running[0]:
        # 更新线程心跳标记，外部可检测线程存活
        THREAD_HEARTBEAT["strong_monitor"] = datetime.now()
        now_day = datetime.now().strftime("%Y%m%d")

        # 跨交易日自动清空开盘10分钟低价缓存，防止隔夜旧数据干扰判断
        if now_day != cache_date:
            stock_10min_low.clear()
            cache_date = now_day
            write_log(f"【缓存重置】交易日切换，清空开盘10分钟低价缓存")

        try:
            # ===================== 模块1：cond1 5日涨幅>cond1_stocks_value%强势股 双分支回撤监控 =====================
            for stock_code in cond1_stocks:
                tick_info = parse_tick_info(stock_code)
                # 行情数据无效，跳过本次循环
                if tick_info is None:
                    continue
                # 解包行情变量
                code = tick_info["code"]
                name = tick_info["name"]
                now_price = tick_info["now"]
                open_p = tick_info["open"]
                open_pct = tick_info["open_pct"]
                day_pct = tick_info["day_pct"]    # 当前日内涨幅
                high_p = tick_info["high"]
                curr_low = tick_info["low"]
                hour = tick_info["hour"]
                minute = tick_info["minute"]
                drawdown = tick_info["drawdown"]
                drawdown_over6 = drawdown < -6  # 回撤幅度超过6%核心条件

                

                # 步骤1：09:30~09:40 更新个股开盘10分钟内最低价缓存
                if hour == 9 and 30 <= minute <= 40:
                    if code not in stock_10min_low:
                        stock_10min_low[code] = curr_low
                    else:
                        if curr_low < stock_10min_low[code]:
                            stock_10min_low[code] = curr_low

                # 步骤2：分支1前置条件判断
                # 条件1：开盘涨跌幅区间 -2% ~ +7%
                branch1_open_range = -5 <= open_pct <= 7
                # 条件2：开盘后最高价超过开盘价+5%（冲高动作）
                rush_5pct_line = open_p * 1.05
                branch1_rush_ok = high_p >= rush_5pct_line
                # 条件3：开盘前10分钟最低价未跌破开盘价，临时注释，不能删除
                #branch1_low_safe = False
                if code in stock_10min_low:
                    ten_min_low = stock_10min_low[code]
                    branch1_low_safe = ten_min_low >= open_p
                # 条件4：时间限制，必须9:40之后才允许触发分支1
                branch1_time_ok = not (hour == 9 and minute <= 40)
                # 分支1完整触发逻辑
                branch1_trigger = branch1_open_range and branch1_rush_ok and branch1_time_ok and drawdown_over6


                # 步骤3：分支2前置条件判断（开盘前5分钟快速杀跌）
                # 修复原BUG：个股不能同时存在cond1和cond3池，原代码判断写反
                branch2_not_both_pool = (code not in cond3_stocks)
                #branch2_not_both_pool = 1
                # 条件1：开盘涨跌幅区间 -2% ~ +9.8%
                branch2_open_range = -2 <= open_pct <= 9.8
                # 条件2：时间限制，仅9:30-9:40开盘前10分钟有效
                branch2_time_ok = (hour == 9 and 30 <= minute <= 40)
                # 分支2完整触发逻辑
                branch2_trigger = branch2_open_range and branch2_time_ok and drawdown_over6 and branch2_not_both_pool

                # 任意分支触发即告警
                total_trigger = branch1_trigger or branch2_trigger
                status_key = f"COND1_{code}"
                # 新增调试输出,临时注释，不能删除
                #old_state = last_status.get(status_key, "不存在")
                #write_log(f"【状态调试】{code} old_state={old_state} new_trigger={total_trigger}")

                # 仅状态发生变化时写入日志，避免循环刷屏
                if status_key not in last_status or last_status[status_key] != total_trigger:
                    last_status[status_key] = total_trigger
                    if total_trigger:
                        abs_draw = abs(drawdown)
                        key_word = get_stock_reason_keyword(code, name, day_pct)
                        if branch1_trigger:
                            
                            # 固定4汉字宽度：超长截断，不足补空格
                            short_name = name[:4]
                            fixed_name1 = short_name.ljust(4, "　")
                            # 开盘10分钟后最大回撤
                            content1 = f"⚠️ 【COND1-冲高跳水】{code:<12} {fixed_name1} | 涨幅{day_pct:>5.1f}% | 最大回撤{abs_draw:>5.1f}% | 关键词：{key_word}"
                            write_log(content1)
                        else:
                            
                            # 固定4汉字宽度：超长截断，不足补空格
                            short_name = name[:4]
                            fixed_name2 = short_name.ljust(4, "　")
                            # 开盘前10分钟快速回撤
                            content2 = f"⚠️ 【COND1-开盘急跌】{code:<12} {fixed_name2} | 涨幅{day_pct:>5.1f}% | 快速回撤{abs_draw:>5.1f}% | 关键词：{key_word}"
                            write_log(content2)

            # ===================== 模块2：cond2 5日涨幅>cond2_stocks_value%龙头股 日内横盘监控（暂时屏蔽，不能删除） =====================
            #for stock_code in cond2_stocks:
            #    tick_info = parse_tick_info(stock_code)
            #    if tick_info is None:
            #        continue
            #    code = tick_info["code"]
            #    name = tick_info["name"]
            #    day_pct = tick_info["day_pct"]  # 日内实时涨幅
                # 横盘条件：日内涨跌幅稳定在-2% ~ +2%
            #    flat_trigger = -2 < day_pct < 2
            #    status_key = f"COND2_{code}"

            #    if status_key not in last_status or last_status[status_key] != flat_trigger:
            #        last_status[status_key] = flat_trigger
            #        if flat_trigger:
            #            write_log(f"📊【COND2-龙头横盘】{code} {name} | 当前日内涨跌幅 {day_pct:.1f}%")

            # ===================== 模块3：cond3 涨停500亿大盘股 高开跳水监控 =====================
            for stock_code in cond3_stocks:
                tick_info = parse_tick_info(stock_code)
                if tick_info is None:
                    continue
                # 解包行情核心变量
                code = tick_info["code"]
                name = tick_info["name"]
                open_pct = tick_info["open_pct"]
                day_pct = tick_info["day_pct"]    # 当前日内涨幅
                hour = tick_info["hour"]
                minute = tick_info["minute"]
                drawdown = tick_info["drawdown"]
                drawdown_over6 = drawdown < -6

                # 前置过滤：仅属于cond3、不在cond1池内的个股
                filter_only_cond3 = (code not in cond1_stocks)
                #filter_only_cond3 = 1
 
                # 条件1：高开区间 6% ~ 10%
                branch3_open_range = 6 <= open_pct <= 10
                # 条件2：时间限制，仅开盘前5分钟9:30-9:35有效
                branch3_time_ok = (hour == 9 and 30 <= minute <= 40)
                # 完整触发条件
                branch3_trigger = filter_only_cond3 and branch3_open_range and branch3_time_ok and drawdown_over6
                status_key = f"COND3_{code}"

                if status_key not in last_status or last_status[status_key] != branch3_trigger:
                    last_status[status_key] = branch3_trigger
                    if branch3_trigger:
                        abs_draw = abs(drawdown)
                        key_word = get_stock_reason_keyword(code, name, day_pct)

                        # 固定4汉字宽度：超长截断，不足补空格
                        short_name = name[:4]
                        fixed_name = short_name.ljust(4, "　")
                        #开盘前10分钟最大回撤
                        content = f"↘️【COND3-涨停急跌】{code:<12} {fixed_name} | 涨幅{day_pct:>5.1f}% | 最大回撤{abs_draw:>5.1f}% | 关键词：{key_word}"
                        write_log(content)

        except Exception:
            # 全局捕获循环异常，单模块崩溃不中断整个监控线程
            pass
        # 每2秒全池扫描一轮，降低接口调用频率
        time.sleep(2)

    # 线程循环结束，安全关闭日志文件释放句柄
    write_log("==================== 强势股监控线程停止 ====================\n\n")
    try:
        log_file.close()
    except Exception:
        pass

# 新增：普通个股高位回撤监控配置
COMMON_DRAWDOWN_THRESHOLD = -6.0   # 回撤大于6%触发
# 记录普通个股上次触发状态，防刷屏
COMMON_STOCK_LAST_STATUS = dict()
# 普通个股回撤日志单独追加，也可共用Log_StrongStock.txt
COMMON_DRAWDOWN_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Log_CommonDrawdown.txt")
def common_stock_high_drawdown_monitor(stock_pool, cond1, cond2, cond3, is_running):
    """
    独立后台线程
    筛选规则：
    1. 股票在总候选池stock_pool内
    2. 该股票 不在cond1、不在cond2、不在cond3 三类强势股内
    3. 日内最高价 大于 开盘价6%
    4. 日内从最高价回撤幅度 >6%
    5. 状态不变不重复打印，仅状态切换写入日志
    """
    
    # 打开日志文件
    log_f = open(COMMON_DRAWDOWN_LOG_PATH, "a", encoding="utf-8")

    def write_common_log(msg):
        try:
            t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            full_msg = f"[{t}] {msg}"
            log_f.write(full_msg + "\n")
            log_f.flush()
            # 同时打印到终端
            print(full_msg)
        except:
            pass

    write_common_log("========== 普通个股高位回撤监测线程启动 ==========")

    while is_running[0]:
        THREAD_HEARTBEAT["common_drawdown_monitor"] = datetime.now()

        now_dt = datetime.now()
        # 直接取系统当前交易时间
        curr_hour = now_dt.hour
        curr_min = now_dt.minute
        # 只在交易时段监控
        if not is_trade_time(curr_hour, curr_min):
            continue
        
        try:
            # 合并三类强势股集合
            strong_set = set(cond1) | set(cond2) | set(cond3)
            # 遍历全候选池
            for code in stock_pool:
                # 核心判定：排除所有强势股
                if code in strong_set:
                    continue

                tick_info = parse_tick_info(code)
                if not tick_info:
                    continue

                name = tick_info["name"]
                open_price = tick_info["open"]
                high_price = tick_info["high"]
                drawdown = tick_info["drawdown"]
                day_pct = tick_info["day_pct"]
                today_amount = tick_info["amount"]               
                # 成交额大于20亿
                if not (20 * 10**8 < today_amount):
                    continue

                # 新增条件：最高价大于开盘价6%
                high_over_open_5pct = high_price > open_price * 1.06
                # 回撤大于6%
                draw_down_enough = drawdown < COMMON_DRAWDOWN_THRESHOLD               
                # 双重条件同时满足才触发
                trigger = high_over_open_5pct and draw_down_enough              
                key = f"COMMON_{code}"

                # 仅状态变化写入日志
                if key not in COMMON_STOCK_LAST_STATUS or COMMON_STOCK_LAST_STATUS[key] != trigger:
                    COMMON_STOCK_LAST_STATUS[key] = trigger
                    if trigger:
                        key_word = get_stock_reason_keyword(code, name, day_pct)
                        abs_down = abs(drawdown)

                        # 固定4汉字宽度：超长截断，不足补空格
                        short_name = name[:4]
                        fixed_name = short_name.ljust(4, "　")
                        content = f"【📉 容量冲高回落】{code:<12} {fixed_name} | 日内涨幅{day_pct:>6.1f}% | 最高回撤{abs_down:>6.1f}% | 关键词：{key_word}"
                        write_common_log(content)

        except Exception:
            pass
        time.sleep(2)

    write_common_log("========== 普通个股高位回撤监测线程停止 ==========\n")
    try:
        log_f.close()
    except:
        pass

# 持仓股监控配置
POSITION_STOCK_TXT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "A_Position_Stock.txt")
# 持仓计时状态存储
POSITION_TIMER_MAP = dict()
def load_position_stocks():
    """从txt加载持仓股票代码，加载完成打印代码+名称确认"""
    pos_list = []
    if not os.path.exists(POSITION_STOCK_TXT):
        print("⚠️ 未找到持仓股配置文件 position_stock.txt")
        return pos_list
    try:
        with open(POSITION_STOCK_TXT, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "." in line:
                pos_list.append(line)
    except Exception as e:
        print(f"❌ 读取持仓文件失败：{e}")
        return pos_list

    # 加载完成后输出列表确认
    if pos_list:
        print("\n======= 已加载持仓监控股票 =======")
        for code in pos_list:
            try:
                name = xtdata.get_instrument_detail(code).get("InstrumentName", "未知名称")
                print(f"{code}  |  {name}")
            except:
                print(f"{code}  |  获取名称失败")
        print("===================================\n")
    else:
        print("ℹ️ 持仓文件内无有效监控股票")

    return pos_list

def position_avg_price_monitor(is_running):
    """
    持仓股均价监控线程
    规则：
    1. 开盘后开始监控持仓股实时日内均价
    2. 现价 < 日内均价 立刻开始计时
    3. 跌破满5分钟未站上均价 → 提示卖出一半
    4. 跌破满10分钟未站上均价 → 提示清仓全部
    5. 10分钟后每间隔5分钟重复提示减仓
    6. 一旦现价重新站上均价 → 清空计时，等待下次跌破重新计时
    7. 提示同时输出终端 + 写入日志文件
    """
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Log_PositionStock.txt")

    # 统一日志函数：终端打印 + 文件写入
    def write_pos_log(msg):
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_msg = f"[{t}] {msg}"
        # 打印到Python终端
        print(full_msg)
        # 写入本地日志文件
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(full_msg + "\n")
        except Exception:
            pass

    write_pos_log("========== 持仓股均价风控监控线程启动 ==========")
    # 加载持仓列表
    pos_codes = load_position_stocks()
    while is_running[0]:
        THREAD_HEARTBEAT["position_monitor"] = datetime.now()
        
        if not pos_codes:
            time.sleep(2)
            continue

        now_dt = datetime.now()
        # 直接取系统当前交易时间
        curr_hour = now_dt.hour
        curr_min = now_dt.minute
        # 只在交易时段监控
        if not is_trade_time3(curr_hour, curr_min):
            continue
        
        for code in pos_codes:
            tick = parse_tick_info(code)
            if not tick:
                continue
            
            code_name = f"{code} {tick['name']}"
            now_price = tick["now"]
           
            # ========== 正确计算日内成交均价 ==========
            full_tick = xtdata.get_full_tick([code]).get(code, {})
            total_vol_hand = full_tick.get("volume", 0.0)
            total_amt = full_tick.get("amount", 0.0)
            if total_vol_hand <= 0:
                continue
            avg_price = total_amt / (total_vol_hand * 100)
            # =========================================

            # 现价站上均价 清除计时
            if now_price >= avg_price:
                if code in POSITION_TIMER_MAP:
                    del POSITION_TIMER_MAP[code]
                    write_pos_log(f"【🟢 持仓风控提醒】{code_name} 现价站上日内均价，取消下跌计时")
                continue

            # 首次跌破均价 初始化计时
            if code not in POSITION_TIMER_MAP:
                POSITION_TIMER_MAP[code] = {
                    "start_time": now_dt,
                    "tip_half": False,
                    "tip_all": False,
                    "last_tip_time": now_dt
                }
                write_pos_log(f"【🟡 持仓风控提醒】{code_name} 现价跌破日内均价，开始下跌计时")

            timer_info = POSITION_TIMER_MAP[code]
            # 计算跌破持续分钟数
            dur_min = (now_dt - timer_info["start_time"]).total_seconds() / 60

            # 跌破满5分钟 提示卖出一半
            if dur_min >= 5 and not timer_info["tip_half"]:
                write_pos_log(f"【🔴 持仓风控提醒】{code_name} 跌破均价已5分钟，建议卖出一半")
                timer_info["tip_half"] = True
                timer_info["last_tip_time"] = now_dt

            # 跌破满10分钟 提示全部清仓
            elif dur_min >= 10 and not timer_info["tip_all"]:
                write_pos_log(f"【🔴 持仓风控提醒】{code_name} 跌破均价已10分钟，建议全部清仓")
                timer_info["tip_all"] = True
                timer_info["last_tip_time"] = now_dt

            # 满10分钟后 每5分钟重复提醒
            elif dur_min >= 10:
                gap_min = (now_dt - timer_info["last_tip_time"]).total_seconds() / 60
                if gap_min >= 5:
                    write_pos_log(f"【🔴 持仓持续弱势】{code_name} 长期低于均价运行，持续规避风险")
                    timer_info["last_tip_time"] = now_dt

        time.sleep(2)

    write_pos_log("========== 持仓股均价风控监控线程停止 ==========\n")


# 全局去重集合
VOL_START_NOTICE_SET = set()
def volume_break_start_monitor(is_running, pool, cond1_stocks, cond2_stocks, cond3_stocks):
    """
    首次放量启动监视线程
    筛选条件：
    1. 仅遍历自定义股票池pool
    2. 排除 cond1 / cond2 / cond3 三类个股
    3. 今日涨幅 ＞11% 且 ＜16%
    4. 当日成交额 20亿 ~ 50亿
    5. 含今日在内三日累计涨跌幅 ＜20%
    6. 10点之后开始监测
    7. 个股只输出一次，终端打印+同步写入日志文件
    """
    # 合并排除集合
    exclude_set = set(cond1_stocks) | set(cond2_stocks) | set(cond3_stocks)
    VOL_BREAK_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Log_VolPriceBreak.txt")
    def write_vol_log(msg):
        """日志写入函数"""
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_msg = f"[{t}] {msg}"
        # 终端打印
        print(full_msg)
        # 写入日志
        try:
            with open(VOL_BREAK_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(full_msg + "\n")
        except:
            pass

    write_vol_log("========== 首次放量启动监视线程启动 ==========")
    while is_running[0]:
        THREAD_HEARTBEAT["volume_break"] = datetime.now()

        now_dt = datetime.now()
        # 直接取系统当前交易时间
        curr_hour = now_dt.hour
        curr_min = now_dt.minute
        # 只在交易时段监控
        if not is_trade_time(curr_hour, curr_min):
            continue

        # 遍历指定股票池pool
        for code in pool:
            
            # 排除指定三类股票 + 已提示过直接跳过
            if code in exclude_set or code in VOL_START_NOTICE_SET:
                continue

            try:
                tick = parse_tick_info(code)
                if not tick:
                    continue
                
                name = tick["name"]
                now_price = tick["now"]
                pre_close = tick["pre_close"]
                today_amount = tick["amount"]
                
                # 今日涨幅 11%~16%
                if pre_close <= 0:
                    continue
                today_pct = (now_price - pre_close) / pre_close
                if not (0.11 < today_pct < 0.16):
                    continue
                # 成交额20亿 - 50亿
                if not (20 * 10**8 < today_amount < 50 * 10**8):
                    continue
                
                df = xtdata.get_market_data(
                    field_list=["close"],
                    stock_list=[code],
                    period="1d",
                    count=5
                )
                
                # df["close"] → DataFrame，index 是 code，columns 是时间
                close_ser = df["close"].iloc[0]  # 这只票的最近K线收盘序列
                if len(close_ser) < 3:
                    continue
                
                close_3d_ago = close_ser.iloc[0]   # 往前取第三根K线（含今日现价）

                three_day_total_pct = (now_price - close_3d_ago) / close_3d_ago
                if three_day_total_pct >= 0.20:
                    continue
                
                key_word = get_stock_reason_keyword(code, name, today_pct)
                # 条件全部满足 终端+日志同步输出
                #content = f"【🚀 右侧放量启动】{code} {name} | 日内涨幅{today_pct:.2%} | 三日涨幅{three_day_total_pct:.2%}，| 关键词：{key_word}"

                
                # 固定4汉字宽度：超长截断，不足补空格
                short_name = name[:4]
                fix_name = short_name.ljust(4, "　")
                # 整条拼接对齐格式
                content = (
                    f"【🚀 右侧放量启动】{code:<12} {fix_name} "
                    f"| 日内涨幅{today_pct:>7.2%} "
                    f"| 三日涨幅{three_day_total_pct:>7.2%} "
                    f"| 关键词：{key_word}"
                )

                write_vol_log(content)
                VOL_START_NOTICE_SET.add(code)

            except Exception:
                continue
        
        time.sleep(3)
    
    VOL_START_NOTICE_SET.clear()
    write_vol_log("🔴 放量启动监测线程已停止")


def get_watch_stock_list(file_path):
    stock_list = []
    if not os.path.exists(file_path):
        return stock_list
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f.readlines():
                line = line.strip()
                if not line:
                    continue
                info = line.split(maxsplit=1)
                if len(info) == 2:
                    stock_list.append((info[0], info[1]))
    except Exception:
        pass
    return stock_list

def append_strength_log(msg):
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Log_StockStrengthYesterday.txt")
    with open(log_file, "a", encoding="utf-8") as fw:
        fw.write(msg + "\n")

# 改用你自己封装的tick解析函数获取涨跌幅
def get_single_stock_rise(stock_code):
    try:
        # 调用你已写好的tick解析函数
        tick_data = parse_tick_info(stock_code)
        pre_close = tick_data.get("pre_close", 0.0)
        last_price = tick_data.get("now", 0.0)
        if pre_close <= 0:
            return 0.0
        rise_percent = (last_price - pre_close) / pre_close * 100
        return round(rise_percent, 2)
    except Exception:
        return 0.0
    
# 对齐版  
def stock_group_strength_monitor():
    base_path = os.path.dirname(os.path.abspath(__file__))
    file_break = os.path.join(base_path, "B_VolPriceBreak.txt")
    file_drawdown = os.path.join(base_path, "B_CommonDrawdown.txt")
    append_strength_log("========== 昨日筛选股票强度监控线程启动 ==========")
    while True:

        now_dt = datetime.now()
        # 直接取系统当前交易时间
        curr_hour = now_dt.hour
        curr_min = now_dt.minute
        # 只在交易时段监控
        if not is_trade_time(curr_hour, curr_min):
            continue

        break_stocks = get_watch_stock_list(file_break)
        down_stocks = get_watch_stock_list(file_drawdown)
        now_time = time.strftime("%Y-%m-%d %H:%M", time.localtime())

        # 放量突破组 排序逻辑不变
        break_info = []
        for code, name in break_stocks:
            rise = get_single_stock_rise(code)
            break_info.append((rise, code, name))
        break_info.sort(reverse=True, key=lambda x: x[0])
        break_avg = round(sum(i[0] for i in break_info)/len(break_info),2) if break_info else 0.0

        # 高位回落组 排序逻辑不变
        down_info = []
        for code, name in down_stocks:
            rise = get_single_stock_rise(code)
            down_info.append((rise, code, name))
        down_info.sort(reverse=True, key=lambda x: x[0])
        down_avg = round(sum(i[0] for i in down_info)/len(down_info),2) if down_info else 0.0

        # 大佬通用对齐方案：固定单元格总宽度，填充全角空格强制对齐
        def get_fixed_cell(name, rise):

            # 固定4汉字宽度：超长截断，不足补空格
            short_name = name[:4]
            name_full = short_name.ljust(4, "　")
            # 涨幅固定格式 正负统一 保留2位小数
            rise_str = f"{rise:6.2f}%"
            # 拼接成固定长度单元格
            return f"{name_full}{rise_str}"

        # 四列竖排 先下后右
        def make_align_text(data_list):
            col = 4
            total = len(data_list)
            if total == 0:
                return ""
            row = (total + col - 1) // col
            lines = []
            for r in range(row):
                row_buf = []
                for c in range(col):
                    idx = r + c * row
                    if idx >= total:
                        continue
                    val, _, n = data_list[idx]
                    row_buf.append(get_fixed_cell(n, val))
                lines.append(" | ".join(row_buf))
            return "\n".join(lines)

        break_show = make_align_text(break_info)
        down_show = make_align_text(down_info)

        # 拼接日志
        log_txt = f"—————————— {now_time} 昨筛选强度监控 ——————————"
        log_txt += f"\n【昨量价突破组】共{len(break_stocks)}只 | 平均涨幅：{break_avg}%"
        if break_show:
            log_txt += f"\n{break_show}"
        log_txt += f"\n【昨冲高回落组】共{len(down_stocks)}只 | 平均涨幅：{down_avg}%"
        if down_show:
            log_txt += "\n" + down_show
        log_txt += "\n"

        append_strength_log(log_txt)
        time.sleep(60)

# 日志股票代码提取交叉去重
def parse_log_stock_filter_with_name():
    """
    功能：
    1. 从 Log_VolPriceBreak.txt、Log_CommonDrawdown.txt 提取 代码+名称
    2. 两份日志都出现的股票，从 VolPriceBreak 剔除，只保留在 CommonDrawdown
    3. 写入：代码  名称
    4. 前置判断：目标文件已有内容则直接退出不重写
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 日志文件
    log_vol_path = os.path.join(base_dir, "Log_VolPriceBreak.txt")
    log_down_path = os.path.join(base_dir, "Log_CommonDrawdown.txt")
    # 输出文件
    out_vol_path = os.path.join(base_dir, "B_VolPriceBreak.txt")
    out_down_path = os.path.join(base_dir, "B_CommonDrawdown.txt")

    # ========== 最前面新增判断：目标文件存在且有内容，直接返回不执行 ==========
    def file_has_content(file_path):
        if not os.path.exists(file_path):
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return bool(f.read().strip())
        except:
            return False

    if file_has_content(out_vol_path) and file_has_content(out_down_path):
        print("📄 目标整理文件已有数据，无需重复生成，直接跳过")
        return
    # ======================================================================

    # 正则：抓 600036.SH 招商银行 这种
    pattern = r'(\d{6}\.(?:SH|SZ|BJ))\s*([^\d\s]+)'

    def read_code_name_set(log_path):
        """读取日志，返回 {(code, name), ...}"""
        s = set()
        if not os.path.exists(log_path):
            return s
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                text = f.read()
            matches = re.findall(pattern, text)
            for code, name in matches:
                s.add((code.strip(), name.strip()))
        except Exception as e:
            print(f"读取 {os.path.basename(log_path)} 异常: {e}")
        return s

    # 读取两组 (code, name)
    vol_set = read_code_name_set(log_vol_path)
    down_set = read_code_name_set(log_down_path)

    # 只按 code 去重（名称跟着 code 走）
    vol_codes = {c for c, n in vol_set}
    down_codes = {c for c, n in down_set}
    inter_codes = vol_codes & down_codes

    # 放量股：不在交集里的
    pure_vol = [(c, n) for c, n in vol_set if c not in inter_codes]
    # 回落股：全部
    all_down = [(c, n) for c, n in down_set]

    # 写入 VolPriceBreak.txt
    with open(out_vol_path, "w", encoding="utf-8") as f:
        for c, n in sorted(pure_vol):
            f.write(f"{c} {n}\n")

    # 写入 CommonDrawdown.txt
    with open(out_down_path, "w", encoding="utf-8") as f:
        for c, n in sorted(all_down):
            f.write(f"{c} {n}\n")

    print(f"✅ 写入完成 | 量价齐升股：{len(pure_vol)} 只 | 容量冲高回落股：{len(all_down)} 只")





def run(pool, cond1_stocks, cond2_stocks, cond3_stocks):
    """主策略运行入口：启动全部后台线程、循环选股"""
    #key_word = get_stock_reason_keyword("600206.SH", "有研新材", 8.19)
    #print(key_word)

    is_running = [True]
    # 启动持仓股均价监控线程，打印到终端和日志，9.30~9:46
    threading.Thread(target=position_avg_price_monitor, args=(is_running,), daemon=True).start()
    time.sleep(0.5)
    # 启动强势股监控线程，打印到日志，全天
    threading.Thread(target=strong_stock_pullback_strategy, args=(cond1_stocks, cond2_stocks, cond3_stocks, is_running), daemon=True).start()
    time.sleep(0.5)
    # 启动容量冲高回落监测线程，打印到终端和日志，全天
    threading.Thread(target=common_stock_high_drawdown_monitor, args=(pool, cond1_stocks, cond2_stocks, cond3_stocks, is_running), daemon=True).start()
    time.sleep(0.5)
    # 启动量价齐升个股监测线程，打印到终端和日志，10.00~
    threading.Thread(target=volume_break_start_monitor, args=(is_running, pool, cond1_stocks, cond2_stocks, cond3_stocks), daemon=True).start()
    time.sleep(0.5)
    #启动昨日筛选股票监控线程，打印到日志，全天
    threading.Thread(target=stock_group_strength_monitor, daemon=True).start()
    
    print("✅ 该版本没有板块刷新/强势股监控/订单流分析")
    
    try:
        while 1:
            time.sleep(3)
    except KeyboardInterrupt:
        print("\n⚠️ 检测到Ctrl+C，准备安全退出程序")
        is_running[0] = False
    print("\n✅ 主策略循环已停止")
    data_center.shutdown()

# =============================================================================
# 模块9：全局常量、路径、账号、策略全局缓存容器
# =============================================================================
# MiniQMT客户端userdata路径
QMT_USERDATA_PATH = r"C:\Users\15113\Desktop\QMT_Software\QMT_DGZQ_Client\东莞证券QMT实盘交易端\userdata_mini"
SESSION_ID = int(time.time())
trade_robot = XtQuantTrader(QMT_USERDATA_PATH, SESSION_ID)
# 交易资金账号
ACCOUNT_ID = "2076018827"
stock_account = StockAccount(ACCOUNT_ID)

# 板块全局容器
STOCK_SECTOR_DICT = {}
SECTOR_STOCK_MAP = {}
SECTOR_RISE_CACHE = {}
SECTOR_INDEX_MAP = {}
# 通达信板块文本文件路径
TDX_BLOCK_FILE = r"C:\Users\15113\Desktop\QMT_Software\TDX\T0002\hq_cache\infoharbor_block.txt"

# 板块黑名单，过滤无效通用板块
BLACK_LIST = {"行业", "指数", "大盘", "小盘", "中证", "上证", "深证", "科创板", "创业板",
              "融资", "融券", "股通", "沪深", "MSCI", "富时", "标普", "道琼斯", "北交所"}

# 策略全局缓存变量
G_SECTOR_MAP = {}
G_SECTOR_STOCK = {}
G_SECTOR_PRICE = {}
G_SECTOR_TOTAL_AMT = {}
G_INIT_FLAG = False

# ====================== 全局监控状态 ======================
# 1. Tick行情监控
TICK_MONITOR = {
    "last_tick_recv_time": datetime.min,  # 最后一次收到Tick时间
    "total_tick_count": 0,                         # 累计接收Tick数据包次数
    "last_minute_tick": deque(maxlen=60),           # 每分钟Tick计数滑动窗口
    "subscribe_total": 0,                          # 当前订阅股票总数
    "warning_limit": 4500,                         # 订阅告警阈值，超过提示接近限流
    "is_flow_limited": False,                      # 是否疑似限流
}

# 2. 所有后台线程心跳记录：key=线程名称，value=最后存活时间
THREAD_HEARTBEAT = {
    "sector_refresh": datetime.min,
    "orderflow_analysis": datetime.min,
    "strong_monitor": datetime.min,
    "main_strategy": datetime.min,
    "common_drawdown_monitor": datetime.min, 
    "position_monitor": datetime.min,
}
# 线程超时判定阈值：超过15秒无心跳判定线程卡死
THREAD_TIMEOUT_SEC = 15

# 3. 监控打印开关，每30秒输出一次健康日志
MONITOR_PRINT_INTERVAL = 30
last_monitor_print = datetime.now()


# 配置
API_URL = "https://api.deepseek.com/v1/chat/completions"
# 缓存：key=股票代码，value=(关键词, 缓存时间戳)
LLM_CACHE: Dict[str, tuple[str, float]] = {}   
# 缓存有效期 300秒=5分钟，避免频繁请求
CACHE_EXPIRE = 300  
# 请求超时
REQ_TIMEOUT = 10   

def get_deepseek_api_key():
    # 获取当前py脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 拼接同级txt配置文件
    txt_path = os.path.join(base_dir, "api_config.txt")
    
    if not os.path.exists(txt_path):
        print("⚠️ 同级目录未找到 api_config.txt 配置文件")
        return ""
    
    try:
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f.readlines():
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip()
    except Exception as e:
        print(f"⚠️ 读取配置失败：{e}")
    return ""

# 同步底层请求
def _sync_get_keyword(stock_code: str, stock_name: str, rise_pct: float) -> str:
    prompt = f"""
【身份】你是A股盘口分析师，只信今日真实财经新闻，拒绝编造。
【任务】只找【{stock_name}({stock_code})】今日{rise_pct}%大涨的**真实催化概念和题材**。
【数据源】必须来自：同花顺股票和通达信股票异动解读。
【输出铁律】
1. 仅输出中文关键词，最多3个，用顿号隔开；
2. 禁止通用词：AI、新能源、国产替代、科技、成长；
3. 禁止解释、禁止理由、禁止多余文字、禁止句子；
4. 找不到真实原因，只输出“未知”。
"""
    DEEPSEEK_API_KEY = get_deepseek_api_key()

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 30,  # 放宽足够放下4个短关键词
        "top_p": 0.1
    }
    import urllib.request, json
    try:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            word = res["choices"][0]["message"]["content"].strip()
            # 过滤违禁通用词
            ban_words = {"AI", "新能源", "国产替代", "科技", "成长"}
            if any(bw in word for bw in ban_words):
                return "未知"
            # 强制截断最长20字符，杜绝长文本
            word = word[:20]
            return word if word else "未知"
    except Exception:
        return "未知"
    
# 异步封装
async def async_get_rise_keyword(stock_code: str, stock_name: str, rise_pct: float) -> str:
    now_ts = time.time()
    if stock_code in LLM_CACHE:
        word, t = LLM_CACHE[stock_code]
        if now_ts - t < CACHE_EXPIRE:
            return word
    loop = asyncio.get_running_loop()
    word = await loop.run_in_executor(None, _sync_get_keyword, stock_code, stock_name, rise_pct)
    LLM_CACHE[stock_code] = (word, now_ts)
    return word

# 清空缓存接口
def clear_llm_cache():
    LLM_CACHE.clear()


# 同步封装函数，随便在哪调用都能用
def get_stock_reason_keyword(code, name, rise):
    return asyncio.run(async_get_rise_keyword(code, name, rise))

# =============================================================================
# 程序入口主函数（一键启动全部流程）
# =============================================================================
if __name__ == "__main__":
    try:
        # 1. 启动MiniQMT交易API
        trade_robot.start()
        time.sleep(1)
        # 2. 连接本地MiniQMT客户端
        conn_code = trade_robot.connect()
        if conn_code != 0:
            print(f"❌ MiniQMT连接失败，错误码：{conn_code}")
            trade_robot.stop()
            exit(1)
        print("✅ 用户2076018827")
        print("✅ MiniQMT客户端连接成功")
        # 3. 查询账户可用资金并打印
        asset_info = trade_robot.query_stock_asset(stock_account)
        if asset_info:
            print(f"✅ 账户可用资金：{asset_info.cash:.2f} 元")
        # 4. 下载板块基础数据
        xtdata.download_sector_data()
        # 5. 获取全市场A股列表
        all_a_shares = xtdata.get_stock_list_in_sector("沪深A股")
        print(f"✅ 全市场A股总数：{len(all_a_shares)} 只")
        # 6. 基础风控过滤，生成候选股票池
        stock_pool = [s for s in all_a_shares if basic_filter(s)]
        print(f"✅ 风控过滤后候选股票池：{len(stock_pool)} 只")
        # 7. 批量下载近6天日线（仅未缓存标的）
        print("✅ 正在批量加载近10天日线数据...")
        batch_download_history(stock_pool, days=10)
        time.sleep(1)
        # 8. 加载通达信板块映射关系
        #init_stock_sector_dict()
        # 9. 批量订阅股票池全部Tick行情
        init_subscribe(stock_pool)
        time.sleep(2.5)
        # 10. 筛选两类强势股，用于后台回调监控
        cond1, cond2, cond3 = filter_strong_stocks_separate(stock_pool)
        # 11. 日志过滤、将一天的量价突破日志和容量冲高回落日志中的代码提取出来
        parse_log_stock_filter_with_name()
        # 12. 启动主策略循环（后台线程+定时选股）
        run(stock_pool, cond1, cond2, cond3)
    except KeyboardInterrupt:
        print("\n⚠️ 用户主动终止程序")

    finally:
        try:
            print("\n正在清理资源...")
            unsubscribe_all()        # 取消行情订阅
            data_center.shutdown()   # 关闭计算线程池
            trade_robot.stop()       # 关闭QMT客户端
        except:
            pass

        print("\n✅ 程序已安全退出")
        
        
        # 🔥 强制结束进程（解决卡住问题）
        #import os
        #os._exit(0)