import os
import urllib.parse
from datetime import datetime, timezone
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="COC 部落战与联赛数据中心",
    page_icon="⚔️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ==========================================
# 手机端与桌面端自适应排版样式
# ==========================================
st.markdown(
    """
    <style>
    /* 顶部标题自适应字号，防止手机端折行占满首屏 */
    h1 {
        font-size: clamp(1.35rem, 4.8vw, 2.05rem) !important;
        line-height: 1.25 !important;
        margin-bottom: 0.25rem !important;
    }
    h2, h3 {
        font-size: clamp(1.08rem, 3.8vw, 1.45rem) !important;
        line-height: 1.3 !important;
    }

    /* 手机端专属紧凑响应式优化 */
    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.85rem !important;
            padding-bottom: 1.5rem !important;
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
        }
        /* 标签页紧凑排列，确保手机单屏可点选 */
        button[data-baseweb="tab"] {
            padding-left: 0.55rem !important;
            padding-right: 0.55rem !important;
            font-size: 0.88rem !important;
        }
        /* 指标卡片在手机端自动排成 2 列网格，避免 4~5 行垂直拉太长 */
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) {
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 0.45rem !important;
        }
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) > div[data-testid="column"],
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) > div[data-testid="stColumn"] {
            flex: 1 1 calc(50% - 0.45rem) !important;
            min-width: calc(50% - 0.45rem) !important;
            width: calc(50% - 0.45rem) !important;
        }
        div[data-testid="stMetric"] {
            background-color: rgba(128, 128, 128, 0.06);
            border: 1px solid rgba(128, 128, 128, 0.14);
            border-radius: 10px;
            padding: 0.55rem 0.7rem !important;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.2rem !important;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 0.78rem !important;
        }
        /* 防止 iOS Safari 点击输入框自动放大页面 */
        input, select, textarea {
            font-size: 16px !important;
        }
        /* 增大按钮触控区域 */
        .stButton > button {
            min-height: 2.5rem !important;
            border-radius: 8px !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# 三个部落配置
CLANS = [
    {"name": "萌面打劫", "tag": "#2YR9JVCG8"},
    {"name": "萌虎下山", "tag": "#2JLC9Q8LL"},
    {"name": "小倔强", "tag": "#2CVRYQ9C"},
]

WAR_HISTORY_FILE = "war_history.csv"
CWL_HISTORY_FILE = "cwl_history.csv"
API_BASE = os.getenv("COC_API_BASE", "https://cocproxy.royaleapi.dev/v1").rstrip("/")


def safe_int(val, default: int = 0) -> int:
    try:
        if pd.isna(val):
            return default
        return int(float(val))
    except Exception:
        return default


def safe_float(val, default: float = 0.0) -> float:
    try:
        if pd.isna(val):
            return default
        return float(val)
    except Exception:
        return default


def normalize_tag(tag: str) -> str:
    t = str(tag or "").strip().upper().replace("O", "0")
    if t and not t.startswith("#"):
        t = "#" + t
    return t


def parse_coc_utc(val: str) -> datetime | None:
    s = str(val or "").strip()
    try:
        if len(s) >= 15 and "T" in s:
            return datetime.strptime(s[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        if len(s) >= 19 and s[4] == "-":
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def is_war_finished(war_state: str, end_time_str: str) -> bool:
    """
    判断对战是否已真正结束：
    - 官方标记为 warEnded -> 已结束
    - 虽然抓拍时还是 inWar，但当前时间已超过 end_time -> 比赛实际已结束，正常计入漏刀
    - 尚未到 end_time 的 inWar 或 preparation -> 正在进行中，暂不计入漏刀
    """
    st_raw = str(war_state or "").strip()
    if st_raw == "warEnded":
        return True
    if st_raw == "inWar":
        end_dt = parse_coc_utc(end_time_str)
        if end_dt is not None and datetime.now(timezone.utc) > end_dt:
            return True
    return False


def get_secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.getenv(key, default).strip()


def format_month_cn(val: str) -> str:
    """将 '2026-11' 或 '20261122T...' 统一格式化为 '2026 11月'"""
    s = str(val or "").strip()
    if len(s) >= 7 and s[4] == "-":
        return f"{s[:4]} {s[5:7]}月"
    if len(s) >= 6 and s[:6].isdigit():
        return f"{s[:4]} {s[4:6]}月"
    return s


def format_date_str(val: str) -> str:
    """将 '20261122T104100.000Z' 转为 '2026-11-22'"""
    s = str(val or "").strip()
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    return s


@st.cache_data(ttl=120)
def load_csv_safe(filepath: str) -> pd.DataFrame:
    if not os.path.exists(filepath):
        return pd.DataFrame()
    try:
        return pd.read_csv(filepath)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120)
def api_get_cached(path: str, token: str) -> tuple[int, dict | None]:
    if not token:
        return 0, None
    url = f"{API_BASE}{path}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            return 200, resp.json()
        return resp.status_code, None
    except Exception:
        return -1, None


def fetch_live_war(clan_tag: str, token: str) -> dict | None:
    enc = urllib.parse.quote(clan_tag)
    code, data = api_get_cached(f"/clans/{enc}/currentwar", token)
    return data if code == 200 else None


def fetch_external_player_live(player_tag: str, token: str) -> dict:
    """实时查询任意玩家档案及其当前所在部落的常规战与七天联赛"""
    clean_tag = normalize_tag(player_tag)
    if not clean_tag or len(clean_tag) < 4:
        return {"error": "请输入有效的玩家标签（例如 #P8QGLU980）。"}
    if not token:
        return {"error": "未配置 COC_API_TOKEN，无法进行实时跨部落接口查询。"}

    enc_p = urllib.parse.quote(clean_tag)
    code, pdata = api_get_cached(f"/players/{enc_p}", token)
    if code == 404 or not pdata:
        return {"error": f"未找到玩家 `{clean_tag}`，请检查标签是否拼写正确（注意数字 0 与字母 O）。"}
    if code != 200:
        return {"error": f"查询失败（HTTP {code}），请稍后重试。"}

    war_hero_stars = 0
    cwl_legend_stars = 0
    for ach in pdata.get("achievements", []) or []:
        aname = ach.get("name", "")
        if aname == "War Hero":
            war_hero_stars = safe_int(ach.get("value", 0))
        elif aname == "War League Legend":
            cwl_legend_stars = safe_int(ach.get("value", 0))

    clan_info = pdata.get("clan") or {}
    cur_clan_tag = clan_info.get("tag", "")
    cur_clan_name = clan_info.get("name", "无部落")

    ext_war_rows = []
    ext_cwl_rows = []
    ext_war_note = ""
    ext_cwl_note = ""

    if cur_clan_tag:
        enc_c = urllib.parse.quote(cur_clan_tag)
        w_code, w_data = api_get_cached(f"/clans/{enc_c}/currentwar", token)
        if w_code == 403:
            ext_war_note = f"该玩家当前所在部落 **{cur_clan_name}** 隐藏了对战日志，无法读取常规战明细。"
        elif w_code == 200 and w_data and w_data.get("state") in ("preparation", "inWar", "warEnded"):
            st_map = {"preparation": "准备日", "inWar": "进行中", "warEnded": "已结束"}
            opp_name = w_data.get("opponent", {}).get("name", "未知对手")
            atk_lim = safe_int(w_data.get("attacksPerMember", 2), 2)
            for m in w_data.get("clan", {}).get("members", []):
                if normalize_tag(m.get("tag", "")) == clean_tag:
                    atks = m.get("attacks", []) or []
                    used = len(atks)
                    ext_war_rows.append({
                        "日期/赛季": f"{format_date_str(w_data.get('startTime', ''))} (当前)",
                        "赛事类型": "常规战",
                        "所属部落": cur_clan_name,
                        "对手部落": opp_name,
                        "顺位": f"#{safe_int(m.get('mapPosition', 0))}",
                        "大本": safe_int(m.get("townhallLevel", 0)),
                        "出刀情况": f"{used} / {atk_lim}",
                        "漏刀标记": f"❌ 漏{max(0, atk_lim - used)}刀" if (w_data.get("state") == "warEnded" and used < atk_lim) else ("⏳ 进行中" if used < atk_lim else "✅ 满刀"),
                        "得星": sum(safe_int(a.get("stars", 0)) for a in atks),
                        "三星数": sum(1 for a in atks if safe_int(a.get("stars", 0)) == 3),
                        "总摧毁(%)": round(sum(safe_float(a.get("destructionPercentage", 0.0)) for a in atks), 1),
                        "状态": st_map.get(w_data.get("state", ""), ""),
                    })

        g_code, g_data = api_get_cached(f"/clans/{enc_c}/currentwar/leaguegroup", token)
        if g_code == 403:
            ext_cwl_note = f"该玩家当前所在部落 **{cur_clan_name}** 隐藏了联赛日志。"
        elif g_code == 200 and g_data and g_data.get("state") != "notInWar":
            season = str(g_data.get("season", ""))
            for r_idx, rnd in enumerate(g_data.get("rounds", []), start=1):
                for w_tag in rnd.get("warTags", []):
                    if not w_tag or w_tag == "#0":
                        continue
                    enc_wt = urllib.parse.quote(w_tag)
                    rw_code, rw_data = api_get_cached(f"/clanwarleagues/wars/{enc_wt}", token)
                    if rw_code != 200 or not rw_data:
                        continue
                    c1 = rw_data.get("clan", {})
                    c2 = rw_data.get("opponent", {})
                    if normalize_tag(c1.get("tag", "")) == cur_clan_tag:
                        our_c, opp_c = c1, c2
                    elif normalize_tag(c2.get("tag", "")) == cur_clan_tag:
                        our_c, opp_c = c2, c1
                    else:
                        continue

                    w_st = rw_data.get("state", "")
                    if w_st in ("inWar", "warEnded"):
                        for m in our_c.get("members", []):
                            if normalize_tag(m.get("tag", "")) == clean_tag:
                                atks = m.get("attacks", []) or []
                                used = len(atks)
                                stars = sum(safe_int(a.get("stars", 0)) for a in atks)
                                dest = sum(safe_float(a.get("destructionPercentage", 0.0)) for a in atks)
                                ext_cwl_rows.append({
                                    "日期/赛季": f"{format_month_cn(season)} · 第{r_idx}天",
                                    "赛事类型": f"七天联赛 D{r_idx}",
                                    "所属部落": cur_clan_name,
                                    "对手部落": opp_c.get("name", "未知对手"),
                                    "顺位": f"#{safe_int(m.get('mapPosition', 0))}",
                                    "大本": safe_int(m.get("townhallLevel", 0)),
                                    "出刀情况": f"{used} / 1",
                                    "漏刀标记": "✅ 满刀" if used > 0 else ("❌ 漏1刀" if w_st == "warEnded" else "⏳ 待出刀"),
                                    "得星": stars,
                                    "三星数": 1 if (used > 0 and stars == 3) else 0,
                                    "总摧毁(%)": round(dest, 1),
                                    "状态": "进行中" if w_st == "inWar" else "已结束",
                                })
                    break

    return {
        "name": pdata.get("name", ""),
        "tag": pdata.get("tag", clean_tag),
        "town_hall": safe_int(pdata.get("townHallLevel", 0)),
        "exp_level": safe_int(pdata.get("expLevel", 0)),
        "clan_name": cur_clan_name,
        "clan_tag": cur_clan_tag,
        "war_pref": "参战 (绿牌)" if pdata.get("warPreference") == "in" else "免战 (红牌)",
        "war_stars_total": safe_int(pdata.get("warStars", 0)),
        "war_hero_stars": war_hero_stars,
        "cwl_legend_stars": cwl_legend_stars,
        "ext_war_rows": ext_war_rows,
        "ext_cwl_rows": ext_cwl_rows,
        "ext_war_note": ext_war_note,
        "ext_cwl_note": ext_cwl_note,
    }


# 顶部标题栏（手机端紧凑单行）
header_col1, header_col2 = st.columns([4, 1])
with header_col1:
    st.title("⚔️ COC 战绩与漏刀中心")
with header_col2:
    if st.button("🔄 刷新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

war_df = load_csv_safe(WAR_HISTORY_FILE)
cwl_df = load_csv_safe(CWL_HISTORY_FILE)

# 第一页更换为「🚨 漏刀成员」，原第一页「实时部落战」合并入第二页「⚔️ 常规战」
tab_missed, tab_war, tab_cwl, tab_member = st.tabs(
    ["🚨 漏刀成员", "⚔️ 常规战", "🏆 七天联赛", "👤 成员查询"]
)

# ==========================================
# Tab 1: 🚨 漏刀成员（核心首屏，适配手机快速点名）
# ==========================================
with tab_missed:
    if war_df.empty and cwl_df.empty:
        st.info("暂无已归档对战数据，等待首次抓拍完成后即可查看漏刀统计。")
    else:
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            m_clan_opts = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
            sel_miss_clan = st.selectbox("筛选部落", m_clan_opts, key="miss_clan_sel")
        with mc2:
            sel_miss_mode = st.selectbox(
                "赛事范围",
                options=["全部 (常规战 + 联赛)", "仅常规战", "仅七天联赛"],
                key="miss_mode_sel",
            )
        with mc3:
            miss_range_map = {
                "近 1 场 (最新结束)": 1,
                "近 5 场": 5,
                "近 10 场": 10,
                "近 15 场": 15,
                "全部已结束场次": None,
            }
            sel_miss_range = st.selectbox(
                "统计范围",
                options=list(miss_range_map.keys()),
                index=3,
                key="miss_range_sel",
            )

        miss_records = []

        # 1) 汇总已结束的常规战
        if not war_df.empty and sel_miss_mode in ("全部 (常规战 + 联赛)", "仅常规战"):
            w_sub = war_df.copy()
            if sel_miss_clan != "全部部落":
                t_tag = sel_miss_clan.split("(")[-1].rstrip(")")
                w_sub = w_sub[w_sub["clan_tag"].astype(str) == t_tag]

            w_sub["is_finished"] = w_sub.apply(
                lambda r: is_war_finished(r.get("war_state", ""), r.get("end_time", "")),
                axis=1,
            )
            w_ended = w_sub[w_sub["is_finished"]].copy()

            n_lim = miss_range_map[sel_miss_range]
            if n_lim is not None and not w_ended.empty:
                kept = []
                for _, grp_c in w_ended.groupby("clan_tag"):
                    c_ids = sorted(grp_c["war_id"].astype(str).unique().tolist())[-n_lim:]
                    kept.append(grp_c[grp_c["war_id"].astype(str).isin(c_ids)])
                w_ended = pd.concat(kept, ignore_index=True) if kept else pd.DataFrame()

            for _, r in w_ended.iterrows():
                used = safe_int(r.get("attacks_used", 0))
                lim = safe_int(r.get("attacks_per_member", 2), 2)
                missed = safe_int(r.get("attacks_missed", max(0, lim - used)))
                miss_records.append({
                    "sort_key": str(r.get("start_time", "")) or str(r.get("war_id", "")),
                    "日期": format_date_str(r.get("start_time", "")),
                    "赛事": "常规战",
                    "所属部落": str(r.get("clan_name", "")),
                    "对手": str(r.get("opponent_name", "")),
                    "player_tag": normalize_tag(r.get("player_tag", "")),
                    "成员名称": str(r.get("player_name", "")),
                    "大本": safe_int(r.get("town_hall", 0)),
                    "顺位": f"#{safe_int(r.get('map_position', 0))}",
                    "实出": used,
                    "应出": lim,
                    "漏刀": missed,
                    "常规漏刀": missed,
                    "联赛漏刀": 0,
                })

        # 2) 汇总已结束的七天联赛场次
        if not cwl_df.empty and sel_miss_mode in ("全部 (常规战 + 联赛)", "仅七天联赛"):
            c_sub = cwl_df.copy()
            if sel_miss_clan != "全部部落":
                t_tag = sel_miss_clan.split("(")[-1].rstrip(")")
                c_sub = c_sub[c_sub["clan_tag"].astype(str) == t_tag]

            c_ended = c_sub[c_sub["war_state"].astype(str) == "warEnded"].copy()
            n_lim = miss_range_map[sel_miss_range]
            if n_lim is not None and not c_ended.empty:
                c_ended["round_key"] = c_ended["season"].astype(str) + "-D" + c_ended["round_num"].astype(int).astype(str).str.zfill(2)
                kept_c = []
                for _, grp_c in c_ended.groupby("clan_tag"):
                    r_ids = sorted(grp_c["round_key"].unique().tolist())[-n_lim:]
                    kept_c.append(grp_c[grp_c["round_key"].isin(r_ids)])
                c_ended = pd.concat(kept_c, ignore_index=True) if kept_c else pd.DataFrame()

            for _, r in c_ended.iterrows():
                used = safe_int(r.get("attacks_used", 0))
                missed = safe_int(r.get("attacks_missed", max(0, 1 - used)))
                rn = safe_int(r.get("round_num", 0))
                sn = str(r.get("season", ""))
                miss_records.append({
                    "sort_key": f"{sn}-D{rn:02d}",
                    "日期": f"{format_month_cn(sn)} D{rn}",
                    "赛事": f"联赛 D{rn}",
                    "所属部落": str(r.get("clan_name", "")),
                    "对手": str(r.get("opponent_name", "")),
                    "player_tag": normalize_tag(r.get("player_tag", "")),
                    "成员名称": str(r.get("player_name", "")),
                    "大本": safe_int(r.get("town_hall", 0)),
                    "顺位": f"#{safe_int(r.get('map_position', 0))}",
                    "实出": used,
                    "应出": 1,
                    "漏刀": missed,
                    "常规漏刀": 0,
                    "联赛漏刀": missed,
                })

        if not miss_records:
            st.info("当前筛选范围内暂无已结束的对战记录。")
        else:
            df_m_all = pd.DataFrame(miss_records)
            df_m_sorted = df_m_all.sort_values("sort_key", ascending=False)
            latest_name_map = df_m_sorted.drop_duplicates("player_tag").set_index("player_tag")["成员名称"].to_dict()
            latest_clan_map = df_m_sorted.drop_duplicates("player_tag").set_index("player_tag")["所属部落"].to_dict()

            only_missed_rows = df_m_sorted[df_m_sorted["漏刀"] > 0]
            last_miss_date_map = only_missed_rows.drop_duplicates("player_tag").set_index("player_tag")["日期"].to_dict()

            agg_miss = (
                df_m_all.groupby("player_tag", as_index=False)
                .agg(
                    大本=("大本", "max"),
                    参战场次=("sort_key", "count"),
                    应出刀=("应出", "sum"),
                    实出刀=("实出", "sum"),
                    总漏刀=("漏刀", "sum"),
                    常规战漏刀=("常规漏刀", "sum"),
                    联赛漏刀=("联赛漏刀", "sum"),
                )
            )
            agg_miss["成员名称"] = agg_miss["player_tag"].map(latest_name_map)
            agg_miss["所属部落"] = agg_miss["player_tag"].map(latest_clan_map)
            agg_miss["最近漏刀"] = agg_miss["player_tag"].map(last_miss_date_map).fillna("—")
            agg_miss["漏刀率(%)"] = (agg_miss["总漏刀"] / agg_miss["应出刀"].replace(0, 1) * 100).round(1)

            offenders = agg_miss[agg_miss["总漏刀"] > 0].sort_values(
                by=["总漏刀", "漏刀率(%)", "大本"], ascending=[False, False, False]
            )

            # 顶部 4 个核心指标（手机端自动 2x2 排列）
            total_miss_attacks = int(offenders["总漏刀"].sum())
            offender_people = len(offenders)
            total_people = len(agg_miss)
            full_attendance_rate = round((1 - offender_people / max(1, total_people)) * 100, 1)

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("漏刀人数", f"{offender_people} 人", delta=f"共 {total_people} 人参战")
            k2.metric("累计漏刀数", f"{total_miss_attacks} 刀")
            k3.metric("零漏刀全勤率", f"{full_attendance_rate}%")
            k4.metric("统计范围", sel_miss_range)

            if offenders.empty:
                st.success("🎉 太棒了！当前统计范围内所有成员全勤满刀，零漏刀记录！")
            else:
                st.subheader(f"📋 漏刀成员排行（共 {offender_people} 人）")
                show_cols_miss = [
                    "成员名称",
                    "所属部落",
                    "总漏刀",
                    "常规战漏刀",
                    "联赛漏刀",
                    "漏刀率(%)",
                    "大本",
                    "最近漏刀",
                    "玩家标签",
                ]
                offenders_disp = offenders.rename(columns={"player_tag": "玩家标签"})[show_cols_miss]
                st.dataframe(offenders_disp, use_container_width=True, hide_index=True)

                # 手机端一键复制群提醒名单
                with st.expander("📲 一键复制漏刀提醒文案（发微信 / QQ群）", expanded=False):
                    lines = [f"⚠️ {sel_miss_clan}（{sel_miss_range}）漏刀统计："]
                    for _, r in offenders.iterrows():
                        lines.append(
                            f"• {r['成员名称']}（{r['所属部落']} {int(r['大本'])}本）：漏 {int(r['总漏刀'])} 刀（实出 {int(r['实出刀'])}/{int(r['应出刀'])}）"
                        )
                    st.code("\n".join(lines), language=None)

            # 逐场漏刀明细
            if not only_missed_rows.empty:
                with st.expander(f"查看逐场漏刀记录明细（共 {len(only_missed_rows)} 条）", expanded=True):
                    detail_m = only_missed_rows.copy()
                    detail_m["出刀"] = detail_m["实出"].astype(str) + "/" + detail_m["应出"].astype(str)
                    detail_cols = ["成员名称", "所属部落", "漏刀", "出刀", "日期", "赛事", "对手", "顺位", "大本"]
                    st.dataframe(detail_m[detail_cols], use_container_width=True, hide_index=True)

# ==========================================
# Tab 2: ⚔️ 常规战（已合并：上半部实时战况 + 下半部常规战归档）
# ==========================================
with tab_war:
    # --- Part A: 实时部落战（原第一页合并于此） ---
    st.subheader("🔥 实时部落战战况")
    api_token = get_secret("COC_API_TOKEN")
    selected_clan_live = st.selectbox(
        "选择查看实时对战部落",
        options=[f"{c['name']} ({c['tag']})" for c in CLANS],
        key="live_clan_select",
    )
    clan_obj_live = CLANS[[f"{c['name']} ({c['tag']})" for c in CLANS].index(selected_clan_live)]

    if not api_token:
        st.info("未检测到 `COC_API_TOKEN`，当前仅展示下方常规战归档历史数据。")
    else:
        live_data = fetch_live_war(clan_obj_live["tag"], api_token)
        if not live_data or live_data.get("state") == "notInWar":
            st.info(f"**{clan_obj_live['name']}** 当前未处于常规部落战中（若在联赛期间请切换至「🏆 七天联赛」）。")
        else:
            state_map = {
                "preparation": "⏳ 准备日",
                "inWar": "🔥 战斗日进行中",
                "warEnded": "🏁 已结束",
            }
            st.markdown(
                f"**{live_data.get('clan', {}).get('name', clan_obj_live['name'])}** 🆚 "
                f"**{live_data.get('opponent', {}).get('name', '未知对手')}**（{state_map.get(live_data.get('state', ''), live_data.get('state', ''))}）"
            )
            c1_info = live_data.get("clan", {})
            c2_info = live_data.get("opponent", {})
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("我方得星", f"{c1_info.get('stars', 0)} ★")
            m2.metric("敌方得星", f"{c2_info.get('stars', 0)} ★")
            m3.metric("我方摧毁率", f"{c1_info.get('destructionPercentage', 0):.1f}%")
            m4.metric("已出刀数", f"{c1_info.get('attacks', 0)} / {live_data.get('teamSize', 0) * live_data.get('attacksPerMember', 2)}")

            atk_limit = safe_int(live_data.get("attacksPerMember", 2), 2)
            live_rows = []
            for m in c1_info.get("members", []):
                atks = m.get("attacks", []) or []
                used = len(atks)
                live_rows.append({
                    "顺位": safe_int(m.get("mapPosition", 0)),
                    "成员名称": m.get("name", ""),
                    "剩余刀": max(0, atk_limit - used),
                    "已出刀": used,
                    "得星": sum(safe_int(a.get("stars", 0)) for a in atks),
                    "大本": safe_int(m.get("townhallLevel", 0)),
                    "总摧毁(%)": round(sum(safe_float(a.get("destructionPercentage", 0.0)) for a in atks), 1),
                    "玩家标签": m.get("tag", ""),
                })
            if live_rows:
                df_live_show = pd.DataFrame(live_rows).sort_values("顺位")
                with st.expander("展开 / 收起实时参战成员出刀明细", expanded=True):
                    st.dataframe(df_live_show, use_container_width=True, hide_index=True)

    st.divider()

    # --- Part B: 常规战归档（原第二页） ---
    st.subheader("📊 常规战历史考勤归档")
    if war_df.empty:
        st.info("暂无常规战归档记录，等待 GitHub Actions 自动抓拍后即可查看。")
    else:
        col_w1, col_w2 = st.columns(2)
        with col_w1:
            clan_opts_w = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
            sel_w_clan = st.selectbox("筛选归档部落", clan_opts_w, key="war_arch_clan")

        range_map = {
            "近 5 场": 5,
            "近 10 场": 10,
            "近 15 场": 15,
            "近 30 场": 30,
            "近 50 场": 50,
            "全部已归档场次": None,
        }
        with col_w2:
            sel_range_label = st.selectbox(
                "统计场次范围",
                options=list(range_map.keys()),
                index=2,
                key="war_range_select",
            )

        sub_war = war_df.copy()
        if sel_w_clan != "全部部落":
            target_tag = sel_w_clan.split("(")[-1].rstrip(")")
            sub_war = sub_war[sub_war["clan_tag"].astype(str) == target_tag]

        sub_war["is_finished"] = sub_war.apply(
            lambda r: is_war_finished(r.get("war_state", ""), r.get("end_time", "")),
            axis=1,
        )
        sub_war["calc_missed"] = sub_war.apply(
            lambda r: safe_int(r.get("attacks_missed", 0)) if r["is_finished"] else 0,
            axis=1,
        )
        sub_war["calc_expected"] = sub_war.apply(
            lambda r: safe_int(r.get("attacks_per_member", 2), 2) if r["is_finished"] else safe_int(r.get("attacks_used", 0)),
            axis=1,
        )

        total_wars_cnt = int(sub_war["war_id"].astype(str).nunique())
        live_ongoing_cnt = int(sub_war[~sub_war["is_finished"]]["war_id"].astype(str).nunique())
        target_n = range_map[sel_range_label]

        if target_n is None:
            sub_war_recent = sub_war.copy()
        else:
            kept_parts = []
            for _, grp_clan in sub_war.groupby("clan_tag"):
                c_wars = sorted(grp_clan["war_id"].astype(str).unique().tolist())[-target_n:]
                kept_parts.append(grp_clan[grp_clan["war_id"].astype(str).isin(c_wars)])
            sub_war_recent = pd.concat(kept_parts, ignore_index=True) if kept_parts else sub_war.copy()

        if live_ongoing_cnt > 0:
            st.caption(f"🔥 当前有 {live_ongoing_cnt} 场部落战正在进行中（未到结束时间，暂不计入漏刀）。")

        if not sub_war_recent.empty:
            summary_w = (
                sub_war_recent.groupby(["clan_name", "player_tag", "player_name"], as_index=False)
                .agg(
                    大本=("town_hall", "max"),
                    参战场次=("war_id", "nunique"),
                    应出刀=("calc_expected", "sum"),
                    实出刀=("attacks_used", "sum"),
                    漏刀=("calc_missed", "sum"),
                    总星=("total_stars", "sum"),
                    三星数=("three_stars", "sum"),
                )
            )
            summary_w["漏刀率(%)"] = (
                summary_w["漏刀"] / summary_w["应出刀"].replace(0, 1) * 100
            ).round(1)
            summary_w = summary_w.sort_values(
                by=["漏刀", "漏刀率(%)", "总星"], ascending=[False, False, False]
            )
            summary_w = summary_w.rename(
                columns={
                    "clan_name": "所属部落",
                    "player_tag": "玩家标签",
                    "player_name": "成员名称",
                }
            )
            ordered_w_cols = [
                "成员名称", "所属部落", "漏刀", "实出刀", "应出刀",
                "总星", "三星数", "大本", "参战场次", "漏刀率(%)", "玩家标签"
            ]
            st.markdown(f"**{sel_range_label}常规战考勤汇总（当前共 {total_wars_cnt} 场）**")
            st.dataframe(summary_w[ordered_w_cols], use_container_width=True, hide_index=True)

            with st.expander("查看逐场原始出刀明细", expanded=False):
                detail_w = sub_war_recent.copy()
                detail_w["日期"] = detail_w["start_time"].apply(format_date_str)
                detail_w["状态说明"] = detail_w.apply(
                    lambda r: "已结束" if r["is_finished"] else ("准备日" if str(r.get("war_state", "")) == "preparation" else "进行中"),
                    axis=1,
                )
                detail_w = detail_w.rename(
                    columns={
                        "clan_name": "所属部落",
                        "opponent_name": "对手部落",
                        "map_position": "顺位",
                        "player_name": "成员名称",
                        "player_tag": "玩家标签",
                        "town_hall": "大本",
                        "attacks_used": "实出刀",
                        "calc_missed": "漏刀",
                        "total_stars": "得星",
                        "three_stars": "三星数",
                        "total_destruction": "总摧毁(%)",
                    }
                )
                cols_show = [
                    "成员名称", "所属部落", "日期", "顺位", "实出刀", "漏刀",
                    "得星", "三星数", "总摧毁(%)", "大本", "对手部落", "状态说明", "玩家标签"
                ]
                cols_show = [c for c in cols_show if c in detail_w.columns]
                st.dataframe(
                    detail_w.sort_values(by=["war_id", "clan_tag", "顺位"], ascending=[False, True, True])[cols_show],
                    use_container_width=True,
                    hide_index=True,
                )

# ==========================================
# Tab 3: 🏆 七天联赛
# ==========================================
with tab_cwl:
    if cwl_df.empty:
        st.info("暂无七天联赛归档记录，联赛开打后系统每 5 分钟会自动抓拍保存。")
    else:
        cwl_work = cwl_df.copy()
        cwl_work["season_label"] = cwl_work["season"].apply(format_month_cn)

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            seasons_raw = sorted(cwl_work["season"].astype(str).unique().tolist(), reverse=True)
            season_map = {format_month_cn(s): s for s in seasons_raw}
            sel_season_label = st.selectbox("选择联赛赛季", list(season_map.keys()), key="cwl_season_sel")
            sel_season_raw = season_map[sel_season_label]
        with col_c2:
            clan_opts_c = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
            sel_c_clan = st.selectbox("选择部落", clan_opts_c, key="cwl_clan_sel")

        sub_cwl = cwl_work[cwl_work["season"].astype(str) == sel_season_raw]
        if sel_c_clan != "全部部落":
            t_tag = sel_c_clan.split("(")[-1].rstrip(")")
            sub_cwl = sub_cwl[sub_cwl["clan_tag"].astype(str) == t_tag]

        if sub_cwl.empty:
            st.warning("该筛选条件下暂无联赛数据。")
        else:
            matrix_rows = []
            for (ctag, cname), grp_c in sub_cwl.groupby(["clan_tag", "clan_name"]):
                players_c = (
                    grp_c.groupby(["player_tag", "player_name"], as_index=False)
                    .agg(
                        大本=("town_hall", "max"),
                        上场天数=("round_num", "nunique"),
                        已出刀=("attacks_used", "sum"),
                        漏打=("attacks_missed", "sum"),
                        总得星=("stars", "sum"),
                    )
                )
                day_dict = {}
                for _, r in grp_c.iterrows():
                    k = (r["player_tag"], safe_int(r["round_num"]))
                    if safe_int(r["attacks_used"]) > 0:
                        day_dict[k] = f"{safe_int(r['stars'])}★"
                    elif str(r["war_state"]) == "warEnded":
                        day_dict[k] = "❌漏"
                    else:
                        day_dict[k] = "⏳待"

                for _, p in players_c.iterrows():
                    pt = p["player_tag"]
                    row_m = {
                        "成员名称": p["player_name"],
                        "部落": cname,
                        "漏打": safe_int(p["漏打"]),
                        "总星": safe_int(p["总得星"]),
                        "满8星": "✅是" if safe_int(p["总得星"]) >= 8 else "未满",
                        "上场": safe_int(p["上场天数"]),
                        "已出刀": safe_int(p["已出刀"]),
                        "大本": safe_int(p["大本"]),
                    }
                    for d in range(1, 8):
                        row_m[f"DAY {d}"] = day_dict.get((pt, d), "—")
                    row_m["玩家标签"] = pt
                    matrix_rows.append(row_m)

            df_matrix = pd.DataFrame(matrix_rows).sort_values(
                by=["漏打", "总星"], ascending=[False, False]
            )
            st.subheader(f"🏆 {sel_season_label} 七天联赛战绩总览")
            st.dataframe(df_matrix, use_container_width=True, hide_index=True)

            with st.expander("查看每日对阵原始明细", expanded=False):
                st.dataframe(
                    sub_cwl.sort_values(by=["clan_tag", "round_num", "map_position"]),
                    use_container_width=True,
                    hide_index=True,
                )

# ==========================================
# Tab 4: 👤 成员查询
# ==========================================
with tab_member:
    search_mode = st.radio(
        "查询方式",
        options=["📋 本群归档成员", "🔍 跨部落标签搜索"],
        horizontal=True,
        key="member_search_mode",
    )

    all_records = []
    if not war_df.empty:
        for _, r in war_df.iterrows():
            used = safe_int(r.get("attacks_used", 0))
            limit = safe_int(r.get("attacks_per_member", 2), 2)
            missed = safe_int(r.get("attacks_missed", max(0, limit - used)))
            stars = safe_int(r.get("total_stars", 0))
            s3 = safe_int(r.get("three_stars", 0))
            dest = safe_float(r.get("total_destruction", 0.0))
            finished = is_war_finished(r.get("war_state", ""), r.get("end_time", ""))
            st_cn = "已结束" if finished else ("准备日" if str(r.get("war_state", "")) == "preparation" else "进行中")

            all_records.append({
                "sort_key": str(r.get("start_time", "")) or str(r.get("war_id", "")),
                "日期/赛季": format_date_str(r.get("start_time", "")),
                "赛事类型": "常规战",
                "所属部落": str(r.get("clan_name", "")),
                "clan_tag": str(r.get("clan_tag", "")),
                "对手部落": str(r.get("opponent_name", "")),
                "player_tag": normalize_tag(r.get("player_tag", "")),
                "player_name": str(r.get("player_name", "")),
                "大本": safe_int(r.get("town_hall", 0)),
                "顺位": f"#{safe_int(r.get('map_position', 0))}",
                "已出刀": used,
                "应出刀": limit if finished else used,
                "出刀情况": f"{used} / {limit}",
                "漏刀": missed if finished else 0,
                "得星": stars,
                "三星数": s3,
                "总摧毁(%)": round(dest, 1),
                "平均摧毁(%)": round(dest / used, 1) if used > 0 else 0.0,
                "状态": st_cn,
            })

    if not cwl_df.empty:
        for _, r in cwl_df.iterrows():
            used = safe_int(r.get("attacks_used", 0))
            missed = safe_int(r.get("attacks_missed", max(0, 1 - used)))
            stars = safe_int(r.get("stars", 0))
            s3 = 1 if (used > 0 and stars == 3) else 0
            dest = safe_float(r.get("destruction", 0.0))
            rn = safe_int(r.get("round_num", 0))
            sn = str(r.get("season", ""))
            st_raw = str(r.get("war_state", ""))
            st_label = "进行中" if st_raw == "inWar" else ("已结束" if st_raw == "warEnded" else st_raw)

            all_records.append({
                "sort_key": f"{sn}-D{rn:02d}",
                "日期/赛季": f"{format_month_cn(sn)} D{rn}",
                "赛事类型": f"联赛 D{rn}",
                "所属部落": str(r.get("clan_name", "")),
                "clan_tag": str(r.get("clan_tag", "")),
                "对手部落": str(r.get("opponent_name", "")),
                "player_tag": normalize_tag(r.get("player_tag", "")),
                "player_name": str(r.get("player_name", "")),
                "大本": safe_int(r.get("town_hall", 0)),
                "顺位": f"#{safe_int(r.get('map_position', 0))}",
                "已出刀": used,
                "应出刀": 1 if st_raw == "warEnded" else used,
                "出刀情况": f"{used} / 1",
                "漏刀": missed if st_raw == "warEnded" else 0,
                "得星": stars,
                "三星数": s3,
                "总摧毁(%)": round(dest, 1),
                "平均摧毁(%)": round(dest, 1) if used > 0 else 0.0,
                "状态": st_label,
            })

    df_all_m = pd.DataFrame(all_records) if all_records else pd.DataFrame()

    if search_mode.startswith("📋"):
        if df_all_m.empty:
            st.info("暂无成员战绩数据，等首次抓拍写入后即可查询。")
        else:
            f_col1, f_col2, f_col3 = st.columns([1.3, 2.2, 1.5])
            with f_col1:
                m_clan_opts = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
                sel_m_clan = st.selectbox("1. 筛选部落", m_clan_opts, key="member_clan_filter")

            df_filtered_clan = df_all_m.copy()
            if sel_m_clan != "全部部落":
                m_ctag = sel_m_clan.split("(")[-1].rstrip(")")
                df_filtered_clan = df_filtered_clan[df_filtered_clan["clan_tag"] == m_ctag]

            latest_players = (
                df_filtered_clan.sort_values("sort_key", ascending=False)
                .drop_duplicates(subset=["player_tag"])
            )
            player_options = []
            tag_lookup = {}
            for _, pr in latest_players.iterrows():
                label = f"{pr['player_name']} ({pr['player_tag']}) · {pr['所属部落']} · {pr['大本']}本"
                player_options.append(label)
                tag_lookup[label] = pr["player_tag"]

            with f_col2:
                if not player_options:
                    st.warning("当前筛选部落下暂无成员记录。")
                    sel_player_label = None
                else:
                    sel_player_label = st.selectbox(
                        "2. 选择成员（支持输入搜索）",
                        options=player_options,
                        key="member_player_select",
                    )

            with f_col3:
                mode_filter = st.selectbox(
                    "3. 赛事范围",
                    options=["全部战绩 (常规+联赛)", "仅常规战", "仅七天联赛"],
                    key="member_mode_filter",
                )

            if sel_player_label:
                chosen_tag = tag_lookup[sel_player_label]
                p_df = df_all_m[df_all_m["player_tag"] == chosen_tag].copy()

                if mode_filter == "仅常规战":
                    p_df = p_df[p_df["赛事类型"] == "常规战"]
                elif mode_filter == "仅七天联赛":
                    p_df = p_df[p_df["赛事类型"].str.startswith("联赛")]

                p_df = p_df.sort_values("sort_key", ascending=False)

                if p_df.empty:
                    st.warning("该成员在所选赛事类型下暂无记录。")
                else:
                    max_rec = len(p_df)
                    recent_k = (
                        st.slider(
                            "查看最近场次数量",
                            min_value=1,
                            max_value=max_rec,
                            value=min(15, max_rec),
                            key="member_recent_k_slider",
                        )
                        if max_rec > 1
                        else 1
                    )
                    p_recent = p_df.head(recent_k).copy()

                    total_matches = len(p_recent)
                    total_used = int(p_recent["已出刀"].sum())
                    total_limit = int(p_recent["应出刀"].sum())
                    total_missed = int(p_recent["漏刀"].sum())
                    total_stars = int(p_recent["得星"].sum())
                    total_3s = int(p_recent["三星数"].sum())
                    avg_stars = round(total_stars / total_used, 2) if total_used > 0 else 0.0
                    rate_3s = round(total_3s / total_used * 100, 1) if total_used > 0 else 0.0
                    avg_dest = round(p_recent[p_recent["已出刀"] > 0]["平均摧毁(%)"].mean(), 1) if total_used > 0 else 0.0

                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric(
                        "出刀 / 漏刀",
                        f"{total_used} / {total_limit} 刀",
                        delta=f"漏 {total_missed} 刀" if total_missed > 0 else "全勤零漏刀",
                        delta_color="inverse" if total_missed > 0 else "normal",
                    )
                    k2.metric("累计得星", f"{total_stars} ★", delta=f"刀均 {avg_stars} ★")
                    k3.metric("三星次数", f"{total_3s} 次", delta=f"三星率 {rate_3s}%")
                    k4.metric("刀均摧毁率", f"{avg_dest}%", delta=f"参战 {total_matches} 场")

                    def fmt_miss(row):
                        if row["状态"] == "进行中":
                            return "⏳ 进行中"
                        return f"❌ 漏{int(row['漏刀'])}刀" if int(row["漏刀"]) > 0 else "✅ 满刀"

                    p_recent["漏刀标记"] = p_recent.apply(fmt_miss, axis=1)
                    display_cols = [
                        "日期/赛季",
                        "赛事类型",
                        "出刀情况",
                        "漏刀标记",
                        "得星",
                        "三星数",
                        "总摧毁(%)",
                        "所属部落",
                        "对手部落",
                        "顺位",
                        "大本",
                        "状态",
                    ]
                    st.subheader(f"📋 {p_recent.iloc[0]['player_name']} 最近 {total_matches} 场明细")
                    st.dataframe(p_recent[display_cols], use_container_width=True, hide_index=True)

    else:
        sc1, sc2 = st.columns([3, 1])
        with sc1:
            input_tag = st.text_input(
                "输入玩家标签（支持不带 #，如 P8QGLU980）",
                placeholder="#XXXXXXXXX",
                key="ext_player_tag_input",
            )
        with sc2:
            do_search = st.button("🔍 立即查询", use_container_width=True)

        if input_tag.strip() or do_search:
            norm_t = normalize_tag(input_tag)
            token_live = get_secret("COC_API_TOKEN")
            res = fetch_external_player_live(norm_t, token_live)

            if "error" in res:
                st.error(res["error"])
            else:
                st.subheader(f"👤 {res['name']} ({res['tag']}) · {res['town_hall']}本")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("当前所在部落", res["clan_name"], delta=res["clan_tag"] or "无部落")
                m2.metric("生涯联赛总星", f"{res['cwl_legend_stars']} ★")
                m3.metric("生涯常规总星", f"{res['war_hero_stars']} ★")
                m4.metric("参战意愿", res["war_pref"])

                if res["ext_cwl_note"]:
                    st.info(res["ext_cwl_note"])
                if res["ext_war_note"]:
                    st.info(res["ext_war_note"])

                live_ext_list = res["ext_cwl_rows"] + res["ext_war_rows"]
                if live_ext_list:
                    st.markdown("#### 🔥 当前所在部落实时战况")
                    st.dataframe(pd.DataFrame(live_ext_list), use_container_width=True, hide_index=True)

                if not df_all_m.empty:
                    local_hist = df_all_m[df_all_m["player_tag"] == res["tag"]].sort_values("sort_key", ascending=False)
                    if not local_hist.empty:
                        local_hist = local_hist.copy()
                        local_hist["漏刀标记"] = local_hist.apply(
                            lambda r: (
                                "⏳ 进行中" if r["状态"] == "进行中"
                                else (f"❌ 漏{int(r['漏刀'])}刀" if int(r["漏刀"]) > 0 else "✅ 满刀")
                            ),
                            axis=1,
                        )
                        disp_c = [
                            "日期/赛季", "赛事类型", "出刀情况", "漏刀标记",
                            "得星", "三星数", "总摧毁(%)", "所属部落", "对手部落", "顺位", "大本", "状态"
                        ]
                        st.markdown(f"#### 📂 在本群历史归档（共 {len(local_hist)} 场）")
                        st.dataframe(local_hist[disp_c], use_container_width=True, hide_index=True)
