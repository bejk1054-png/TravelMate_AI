"""旅遊網站視覺與結果卡片；只負責顯示後端回傳資料。"""
from html import escape
from urllib.parse import urlparse
import pandas as pd
import streamlit as st


def setup_style():
    """以原生 Streamlit 元件保留鍵盤操作與手機排版。"""
    st.markdown('''<style>
    .stApp {background:#f8f7f3;color:#193b43;}
    .block-container {max-width:1180px;padding-top:2.4rem;padding-bottom:3rem;}
    h1,h2,h3 {letter-spacing:-.025em;color:#193b43;}
    [data-testid="stSidebar"] {background:#ecefe9;}
    [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] {border-radius:18px;}
    [data-testid="stForm"] {background:white;padding:24px;border:1px solid #dce4df;}
    .stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"] {background:#126c66;border-color:#126c66;border-radius:10px;}
    .stTabs [data-baseweb="tab-list"] {gap:24px;margin-bottom:18px;}
    .stTabs [aria-selected="true"] {color:#126c66;}
    .tm-hero {background:#193b43;border-radius:24px;padding:38px 40px;margin-bottom:28px;color:#fff;position:relative;overflow:hidden;}
    .tm-hero:after {content:'↗';position:absolute;right:35px;top:0;color:#8fc6b3;font-size:160px;opacity:.25;}
    .tm-hero h1 {color:#fff!important;font-size:clamp(30px,4vw,48px);line-height:1.2;max-width:700px;margin:14px 0;}
    .tm-hero p {color:#d3e3df;max-width:650px;line-height:1.8;margin:0;}
    .tm-eyebrow {font-size:12px;letter-spacing:.16em;color:#a8d7c5;font-weight:700;}
    .tm-card {padding:8px 0 12px;}
    .tm-card h3 {font-size:21px;margin:8px 0;overflow-wrap:anywhere;}
    .tm-tag {display:inline-block;background:#e8f2ed;color:#126c66;padding:5px 10px;border-radius:7px;font-size:12px;}
    .tm-muted {color:#667e80;font-size:14px;line-height:1.7;}
    .tm-price {font-size:22px;font-weight:650;color:#193b43;}
    .tm-empty {padding:30px;border:1px dashed #b7cbc2;border-radius:18px;background:#eef3ee;color:#48615e;}
    [data-testid="stMetric"] {background:white;border:1px solid #dde5df;border-radius:16px;padding:18px;}
    @media(max-width:640px){.block-container{padding-top:1.3rem;}.tm-hero{padding:26px 22px;}.tm-hero:after{right:8px;font-size:110px;}}
    </style>''', unsafe_allow_html=True)
    st.markdown('''<div class="tm-hero"><span class="tm-eyebrow">TRAVELMATE AI · YOUR NEXT JOURNEY</span>
    <h1>下一趟旅行，<br>從你的期待開始。</h1>
    <p>找值得去的地方、挑適合的住宿，把行程與預算放在一起考慮。<br>輸入目的地，開始規劃屬於你的旅程。</p></div>''', unsafe_allow_html=True)


def safe_text(value):
    """所有外部文字先跳脫，避免地名或 API 內容被當成 HTML。"""
    return escape(str(value if value is not None else '待確認'))


def link(label, url):
    """只允許一般網頁連結，不把不明 URL 送入頁面。"""
    if isinstance(url, str) and urlparse(url).scheme in {'http', 'https'}:
        st.link_button(label, url, use_container_width=True)


def card(title, tag, detail, price):
    st.markdown(f'<div class="tm-card"><span class="tm-tag">{safe_text(tag)}</span>'
                f'<h3>{safe_text(title)}</h3><div class="tm-muted">{safe_text(detail)}</div>'
                f'<p class="tm-price">{safe_text(price)}</p></div>', unsafe_allow_html=True)


def render_plan(result):
    """將同一份結果呈現為行程卡、住宿卡及預算摘要，保留來源與未知費用。"""
    spending = result['spending']
    st.subheader(f"你的旅程 · {result.get('area', result['destination'])}")
    cols = st.columns(3)
    cols[0].metric('可核對景點', f"{len(result['spots'])} 個")
    cols[1].metric('住宿選項', f"{len(result['hotels'])} 間")
    cols[2].metric('完整估算' if spending['total'] is not None else '目前部分估算',
                   f"NT$ {spending['total'] if spending['total'] is not None else spending['known_subtotal']:,.0f}")
    for warning in result.get('warnings', []):
        st.info(warning)
    with st.expander('資料來源與查價狀態'):
        st.write(result['data_notice'])
        st.caption(result.get('spot_message', ''))
        st.caption(result.get('booking', {}).get('message', ''))
    overview, hotels, spots, costs = st.tabs(['每日行程', '住宿精選', '探索景點', '預算與建議'])
    with overview:
        rows = result['itinerary']
        if not rows:
            st.info('目前沒有取得可核實的景點。請確認地名、加上國家後重新查詢。')
        else:
            frame = pd.DataFrame(rows)
            for day, daily in frame.groupby('day', sort=True):
                with st.container(border=True):
                    st.markdown(f"### 第 {int(day):02d} 天 · {daily.iloc[0]['date']}")
                    for row in daily.to_dict('records'):
                        a, b = st.columns([4, 1])
                        with a:
                            fee = row.get('cost_twd_per_person')
                            card(row['spot'], row['time'], row['activity'],
                                 f'每人 NT$ {fee:,.0f}' if fee is not None else '門票／活動費待查')
                            if row.get('travel_minutes_estimate'):
                                st.caption(f"至此站移動約 {row['travel_minutes_estimate']} 分鐘（座標估算）")
                        with b:
                            link('查看地圖', row.get('google_maps_url') or row.get('map_url'))
            covered = {row['day'] for row in rows}
            st.caption(f'目前取得 {len(rows)} 筆景點安排，涵蓋 {len(covered)} 天；其餘天數請再補充安排。移動時間請核對實際路線。')
            with st.expander('下載行程表'):
                download = frame[['day', 'date', 'time', 'spot', 'activity', 'cost_twd_per_person', 'fee_note']].rename(columns={
                    'day':'天數','date':'日期','time':'時間','spot':'景點','activity':'活動','cost_twd_per_person':'每人費用（TWD）','fee_note':'費用說明'})
                st.download_button('下載 CSV', download.to_csv(index=False).encode('utf-8-sig'), 'travelmate-itinerary.csv', 'text/csv')
    with hotels:
        st.caption('住宿名稱可核對；實際房價與可訂性請以訂房頁為準。')
        if not result['hotels']:
            st.info('目前沒有取得住宿名稱，可直接到 Booking 查價。')
        columns = st.columns(2)
        for index, hotel in enumerate(result['hotels']):
            with columns[index % 2], st.container(border=True):
                price = hotel.get('price')
                card(hotel['name'], '住宿選項', hotel.get('room_type') or '房型待確認',
                     f"NT$ {price:,.0f}／晚" if price is not None else '即時房價待查')
                if hotel.get('room_size') is not None:
                    size = float(hotel['room_size'])
                    st.caption(f'房間 {size:g} 平方公尺 · 約 {size / 3.305785:.1f} 坪')
                st.caption(hotel.get('price_source') or '請核對住宿來源')
                link('查看住宿位置', hotel.get('map_url'))
                link('前往訂房', hotel.get('booking_url') or result.get('booking_search_url'))
        link('在 Booking 搜尋更多住宿', result.get('booking_search_url'))
    with spots:
        columns = st.columns(2)
        categories = {'museum':'博物館','park':'公園','monument':'紀念地標','gallery':'藝廊','viewpoint':'觀景點','castle':'古蹟','zoo':'動物園','attraction':'景點','restaurant':'餐廳','marketplace':'市場','memorial':'紀念地標'}
        if not result['spots']:
            st.info('目前查無可核實景點，請調整目的地後重試。')
        for index, spot in enumerate(result['spots']):
            with columns[index % 2], st.container(border=True):
                rating = spot.get('rating')
                detail = f"Google 評分 {rating} · {spot.get('rating_count') or 0} 則評論" if rating is not None else '公開地點資料 · Google 評分待核對'
                fee = spot.get('cost_twd_per_person')
                card(spot['name'], categories.get(spot.get('category'), '探索景點'), detail,
                     f'每人 NT$ {fee:,.0f}' if fee is not None else '門票／活動費待查')
                link('查看景點與路線', spot.get('google_maps_url') or spot.get('map_url'))
                # Google 提供者標示保留在對應景點，不能隱藏來源。
                for attribution in spot.get('attributions', []):
                    if attribution.get('provider'):
                        st.caption(f"資料提供者：{attribution['provider']}")
                        link('提供者網站', attribution.get('providerUri'))
    with costs:
        left, right = st.columns([1, 1])
        with left, st.container(border=True):
            st.subheader('旅程預算')
            if spending['total'] is None:
                st.info('尚缺 ' + '、'.join(spending['unknown_costs']) + ' 費用，剩餘預算待確認。')
            else:
                st.metric('剩餘預算', f"NT$ {spending['remaining']:,.0f}")
            st.bar_chart(pd.Series({k:v for k,v in spending['components'].items() if v is not None}, name='TWD'), color='#126c66')
            st.caption(spending['assumptions'])
        with right, st.container(border=True):
            st.subheader('旅途建議')
            st.caption(result['advice']['source'])
            if result['advice'].get('status') != 'connected':
                st.caption('目前提供規則式建議，AI 尚未連線。')
            st.write(result['advice']['text'])
            for name, info in result.get('external', {}).items():
                if name == 'weather' and info.get('available'):
                    st.write(f"天氣 {info['min_c']}–{info['max_c']}°C · 降雨機率 {info['rain_probability']}%")
                elif name == 'currency' and info.get('rate') is not None:
                    st.write(f"匯率 1 {info['base']} ≈ {info['rate']} {info['quote']}")
                    st.caption(f"更新時間：{info.get('date', '待確認')}")
                else:
                    st.caption(info.get('message', '即時資訊待查'))
    with st.expander('相關旅遊筆記與處理資訊'):
        st.write(' → '.join(result['tool_trace']))
        st.json(result['rag_sources'])
