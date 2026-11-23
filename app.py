import os
import urllib.parse
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="COC 部落战与联赛战绩追踪",
    page_icon="⚔️",
    layout="wide",
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
def fetch_live_war(clan_tag: str, token: str) -> dict | None:
    if not token:
        return None
    enc = urllib.parse.quote(clan_tag)
    url = f"{API_BASE}/clans/{enc}/currentwar"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        return None
    return None


# 顶部简洁标题
header_col1, header_col2 = st.columns([4, 1])
with header_col1:
    st.title("⚔️ COC 部落战与联赛数据中心")
with header_col2:
    st.write("")
    if st.button("🔄 刷新最新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

war_df = load_csv_safe(WAR_HISTORY_FILE)
cwl_df = load_csv_safe(CWL_HISTORY_FILE)

# 四个窗口：「👤 成员战绩查询」紧挨在「🏆 七天联赛」隔壁
tab_live, tab_war, tab_cwl, tab_member = st.tabs(
    ["⚔️ 实时部落战", "📊 常规战归档", "🏆 七天联赛", "👤 成员战绩查询"]
)

# ==========================================
# Tab 1: 实时部落战
# ==========================================
with tab_live:
    api_token = get_secret("COC_API_TOKEN")
    selected_clan_live = st.selectbox(
        "选择查看部落",
        options=[f"{c['name']} ({c['tag']})" for c in CLANS],
        key="live_clan_select",
    )
    clan_obj_live = CLANS[[f"{c['name']} ({c['tag']})" for c in CLANS].index(selected_clan_live)]

    if not api_token:
        st.info("未检测到 `COC_API_TOKEN`，当前仅展示下方归档标签页中的历史数据；如需实时刷新，请在 Streamlit Secrets 中添加 `COC_API_TOKEN`。")
    else:
        live_data = fetch_live_war(clan_obj_live["tag"], api_token)
        if not live_data or live_data.get("state") == "notInWar":
            st.warning(f"**{clan_obj_live['name']}** 当前未处于常规部落战中（或处于七天联赛期间，请切换至「🏆 七天联赛」查看）。")
        else:
            state_map = {
                "preparation": "⏳ 准备日",
                "inWar": "🔥 战斗日进行中",
                "warEnded": "🏁 已结束",
            }
            st.subheader(
                f"{live_data.get('clan', {}).get('name', clan_obj_live['name'])} 🆚 "
                f"{live_data.get('opponent', {}).get('name', '未知对手')}（{state_map.get(live_data.get('state', ''), live_data.get('state', ''))}）"
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
                    "大本": safe_int(m.get("townhallLevel", 0)),
                    "成员名称": m.get("name", ""),
                    "玩家标签": m.get("tag", ""),
                    "已出刀": used,
                    "剩余刀": max(0, atk_limit - used),
                    "得星": sum(safe_int(a.get("stars", 0)) for a in atks),
                    "总摧毁(%)": round(sum(safe_float(a.get("destructionPercentage", 0.0)) for a in atks), 1),
                })
            if live_rows:
                df_live_show = pd.DataFrame(live_rows).sort_values("顺位")
                st.dataframe(df_live_show, use_container_width=True, hide_index=True)

# ==========================================
# Tab 2: 常规战归档
# ==========================================
with tab_war:
    if war_df.empty:
        st.info("暂无常规战归档记录，等待 GitHub Actions 自动抓拍后即可查看。")
    else:
        col_w1, col_w2 = st.columns([2, 2])
        with col_w1:
            clan_opts_w = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
            sel_w_clan = st.selectbox("筛选部落", clan_opts_w, key="war_arch_clan")
        sub_war = war_df.copy()
        if sel_w_clan != "全部部落":
            target_tag = sel_w_clan.split("(")[-1].rstrip(")")
            sub_war = sub_war[sub_war["clan_tag"].astype(str) == target_tag]

        unique_wars = sorted(sub_war["war_id"].astype(str).unique().tolist())
        total_wars_cnt = max(1, len(unique_wars))
        with col_w2:
            if total_wars_cnt > 1:
                recent_n_wars = st.slider(
                    "统计最近场次",
                    min_value=1,
                    max_value=total_wars_cnt,
                    value=min(15, total_wars_cnt),
                    key="war_recent_slider",
                )
            else:
                recent_n_wars = 1
                st.caption("当前已归档 1 场常规战")

        keep_war_ids = unique_wars[-recent_n_wars:]
        sub_war_recent = sub_war[sub_war["war_id"].astype(str).isin(keep_war_ids)]

        if not sub_war_recent.empty:
            summary_w = (
                sub_war_recent.groupby(["clan_name", "player_tag", "player_name"], as_index=False)
                .agg(
                    大本=("town_hall", "max"),
                    参战场次=("war_id", "nunique"),
                    应出刀=("attacks_per_member", "sum"),
                    实出刀=("attacks_used", "sum"),
                    漏刀=("attacks_missed", "sum"),
                    总星=("total_stars", "sum"),
                    三星数=("three_stars", "sum"),
                )
            )
            summary_w["漏刀率(%)"] = (summary_w["漏刀"] / summary_w["应出刀"].replace(0, 1) * 100).round(1)
            summary_w = summary_w.sort_values(by=["漏刀", "漏刀率(%)", "总星"], ascending=[False, False, False])
            st.subheader(f"近 {len(keep_war_ids)} 场常规战考勤汇总")
            st.dataframe(summary_w, use_container_width=True, hide_index=True)

            with st.expander("查看逐场原始出刀明细", expanded=False):
                detail_w = sub_war_recent.copy()
                detail_w["日期"] = detail_w["start_time"].apply(format_date_str)
                cols_show = [
                    "日期", "clan_name", "opponent_name", "map_position",
                    "player_name", "player_tag", "town_hall", "attacks_used",
                    "attacks_missed", "total_stars", "three_stars", "total_destruction", "war_state"
                ]
                cols_show = [c for c in cols_show if c in detail_w.columns]
                st.dataframe(
                    detail_w.sort_values(by=["war_id", "clan_tag", "map_position"], ascending=[False, True, True])[cols_show],
                    use_container_width=True,
                    hide_index=True,
                )

# ==========================================
# Tab 3: 七天联赛
# ==========================================
with tab_cwl:
    if cwl_df.empty:
        st.info("暂无七天联赛归档记录，联赛开打后系统每 30 分钟会自动抓拍保存。")
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
                        "部落": cname,
                        "成员名称": p["player_name"],
                        "玩家标签": pt,
                        "大本": safe_int(p["大本"]),
                        "上场": safe_int(p["上场天数"]),
                        "已出刀": safe_int(p["已出刀"]),
                        "漏打": safe_int(p["漏打"]),
                        "总星": safe_int(p["总得星"]),
                        "满8星": "✅是" if safe_int(p["总得星"]) >= 8 else "未满",
                    }
                    for d in range(1, 8):
                        row_m[f"DAY {d}"] = day_dict.get((pt, d), "—")
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
# Tab 4: 👤 成员战绩查询（七天联赛隔壁的新窗口）
# ==========================================
with tab_member:
    all_records = []

    # 1. 整合常规战记录
    if not war_df.empty:
        for _, r in war_df.iterrows():
            used = safe_int(r.get("attacks_used", 0))
            limit = safe_int(r.get("attacks_per_member", 2), 2)
            missed = safe_int(r.get("attacks_missed", max(0, limit - used)))
            stars = safe_int(r.get("total_stars", 0))
            s3 = safe_int(r.get("three_stars", 0))
            dest = safe_float(r.get("total_destruction", 0.0))
            st_raw = str(r.get("war_state", ""))
            st_label = "进行中" if st_raw == "inWar" else ("已结束" if st_raw == "warEnded" else st_raw)

            all_records.append({
                "sort_key": str(r.get("start_time", "")) or str(r.get("war_id", "")),
                "日期/赛季": f"{format_date_str(r.get('start_time', ''))} ({format_month_cn(r.get('start_time', ''))})",
                "赛事类型": "常规战",
                "所属部落": str(r.get("clan_name", "")),
                "clan_tag": str(r.get("clan_tag", "")),
                "对手部落": str(r.get("opponent_name", "")),
                "player_tag": str(r.get("player_tag", "")),
                "player_name": str(r.get("player_name", "")),
                "大本": safe_int(r.get("town_hall", 0)),
                "顺位": f"#{safe_int(r.get('map_position', 0))}",
                "已出刀": used,
                "应出刀": limit,
                "出刀情况": f"{used} / {limit}",
                "漏刀": missed,
                "得星": stars,
                "三星数": s3,
                "总摧毁(%)": round(dest, 1),
                "平均摧毁(%)": round(dest / used, 1) if used > 0 else 0.0,
                "状态": st_label,
            })

    # 2. 整合七天联赛记录
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
                "日期/赛季": f"{format_month_cn(sn)} · 第{rn}天",
                "赛事类型": f"七天联赛 D{rn}",
                "所属部落": str(r.get("clan_name", "")),
                "clan_tag": str(r.get("clan_tag", "")),
                "对手部落": str(r.get("opponent_name", "")),
                "player_tag": str(r.get("player_tag", "")),
                "player_name": str(r.get("player_name", "")),
                "大本": safe_int(r.get("town_hall", 0)),
                "顺位": f"#{safe_int(r.get('map_position', 0))}",
                "已出刀": used,
                "应出刀": 1,
                "出刀情况": f"{used} / 1",
                "漏刀": missed,
                "得星": stars,
                "三星数": s3,
                "总摧毁(%)": round(dest, 1),
                "平均摧毁(%)": round(dest, 1) if used > 0 else 0.0,
                "状态": st_label,
            })

    if not all_records:
        st.info("暂无成员战绩数据，等首次抓拍写入后即可在此查询任意成员的近期表现。")
    else:
        df_all_m = pd.DataFrame(all_records)

        f_col1, f_col2, f_col3 = st.columns([1.3, 2.2, 1.5])
        with f_col1:
            m_clan_opts = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
            sel_m_clan = st.selectbox("1. 筛选部落", m_clan_opts, key="member_clan_filter")

        df_filtered_clan = df_all_m.copy()
        if sel_m_clan != "全部部落":
            m_ctag = sel_m_clan.split("(")[-1].rstrip(")")
            df_filtered_clan = df_filtered_clan[df_filtered_clan["clan_tag"] == m_ctag]

        # 按最新战绩去重生成可选成员列表（支持在下拉框内直接打字搜索名字或标签）
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
                    "2. 选择成员（可直接输入名字搜索）",
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
                p_df = p_df[p_df["赛事类型"].str.startswith("七天联赛")]

            p_df = p_df.sort_values("sort_key", ascending=False)

            if p_df.empty:
                st.warning("该成员在所选赛事类型下暂无记录。")
            else:
                max_rec = len(p_df)
                if max_rec > 1:
                    recent_k = st.slider(
                        "查看最近场次数量",
                        min_value=1,
                        max_value=max_rec,
                        value=min(15, max_rec),
                        key="member_recent_k_slider",
                    )
                else:
                    recent_k = 1

                p_recent = p_df.head(recent_k).copy()

                # 核心指标卡片
                total_matches = len(p_recent)
                total_used = int(p_recent["已出刀"].sum())
                total_limit = int(p_recent["应出刀"].sum())
                total_missed = int(p_recent["漏刀"].sum())
                total_stars = int(p_recent["得星"].sum())
                total_3s = int(p_recent["三星数"].sum())
                avg_stars = round(total_stars / total_used, 2) if total_used > 0 else 0.0
                rate_3s = round(total_3s / total_used * 100, 1) if total_used > 0 else 0.0
                avg_dest = round(p_recent[p_recent["已出刀"] > 0]["平均摧毁(%)"].mean(), 1) if total_used > 0 else 0.0

                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("近期参战", f"{total_matches} 场")
                k2.metric(
                    "出刀 / 漏刀",
                    f"{total_used} / {total_limit} 刀",
                    delta=f"漏 {total_missed} 刀" if total_missed > 0 else "全勤零漏刀",
                    delta_color="inverse" if total_missed > 0 else "normal",
                )
                k3.metric("累计得星", f"{total_stars} ★", delta=f"刀均 {avg_stars} ★")
                k4.metric("三星次数", f"{total_3s} 次", delta=f"三星率 {rate_3s}%")
                k5.metric("刀均摧毁率", f"{avg_dest}%")

                # 近期逐场明细表
                p_recent["漏刀标记"] = p_recent["漏刀"].apply(lambda x: f"❌ 漏{x}刀" if x > 0 else "✅ 满刀")
                display_cols = [
                    "日期/赛季",
                    "赛事类型",
                    "所属部落",
                    "对手部落",
                    "顺位",
                    "大本",
                    "出刀情况",
                    "漏刀标记",
                    "得星",
                    "三星数",
                    "总摧毁(%)",
                    "状态",
                ]
                st.subheader(f"📋 {p_recent.iloc[0]['player_name']} 最近 {total_matches} 场战绩明细")
                st.dataframe(p_recent[display_cols], use_container_width=True, hide_index=True)
