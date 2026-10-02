"""旅遊網站視覺與結果卡片；只負責顯示後端回傳資料。"""
from html import escape
from pathlib import Path
from base64 import b64encode
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st


def setup_style():
    """載入專案內的樣式與原創旅行插畫，不依賴外部圖片服務。"""
    assets = Path(__file__).resolve().parent / 'assets'
    css = (assets / 'theme.css').read_text(encoding='utf-8')
    artwork = b64encode((assets / 'journey.svg').read_bytes()).decode('ascii')
    st.markdown('<style>' + css + '</style>', unsafe_allow_html=True)
    st.markdown(f'''<div class="tm-brand"><div class="tm-logo">TravelMate<span> / AI</span></div><div class="tm-brand-note">好好計畫，慢慢旅行</div></div>
<div class="tm-hero"><div><span class="tm-eyebrow">A LITTLE PLAN. A BIG ADVENTURE.</span><h1>把日子留給<br><em>值得期待的風景。</em></h1><p>從一個想去的地方開始，找到心動的景點、適合的住宿，和剛剛好的旅行節奏。</p><div class="tm-tags"><span>景點探索</span><span>住宿查價</span><span>旅費規劃</span></div></div><div class="tm-hero-art"><img src="data:image/svg+xml;base64,{artwork}" alt="山岳、湖泊與蜿蜒步道的原創旅行插畫"/><div class="tm-stamp">TAKE THE SCENIC ROUTE<br>讓旅程，多一點期待。</div></div></div>''', unsafe_allow_html=True)


def safe_text(value):
    """所有外部文字先跳脫，避免地名或 API 內容被當成 HTML。"""
    return escape(str(value if value is not None else '待確認'))


def link(label, url):
    """只允許一般網頁連結，不把不明 URL 送入頁面。"""
    if isinstance(url, str):
        try:
            parsed = urlparse(url)
            valid = parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
        except ValueError:
            valid = False
        if valid:
            st.link_button(label, url, use_container_width=True)


def card(title, tag, detail, price):
    st.markdown(f'<div class="tm-card"><span class="tm-tag">{safe_text(tag)}</span>'
                f'<h3>{safe_text(title)}</h3><div class="tm-muted">{safe_text(detail)}</div>'
                f'<p class="tm-price">{safe_text(price)}</p></div>', unsafe_allow_html=True)


def hotel_search_url(base_url, name, area):
    """沿用入住條件搜尋具名住宿；搜尋結果不等於已確認可訂房源。"""
    try:
        parsed = urlparse(base_url or '')
        if parsed.scheme != 'https' or parsed.hostname not in {'www.booking.com', 'booking.com'}:
            return None
        query = parse_qs(parsed.query)
        query['ss'] = [f'{name}, {area}']
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
    except ValueError:
        return None


def render_plan(result):
    """將同一份結果呈現為行程卡、住宿卡及預算摘要，保留來源與未知費用。"""
    spending = result['spending']
    st.subheader(f"你的旅程 · {result.get('area', result['destination'])}")
    trip = result.get('trip', {})
    if trip:
        st.caption(f"{trip['start_date']} 出發 · {trip['days']} 天 · {trip['people']} 人 · 預算 NT$ {trip['budget_twd']:,.0f} · {trip['preference']}")
    if result.get('generated_at'):
        updated = datetime.fromisoformat(result['generated_at']).astimezone(ZoneInfo('Asia/Taipei'))
        st.caption(f"查詢時間：{updated:%Y-%m-%d %H:%M}（台灣時間）；價格與營業狀態請核對來源。")
    cols = st.columns(3)
    cols[0].metric('可核對景點', f"{len(result['spots'])} 個")
    cols[1].metric('住宿選項', f"{len(result['hotels'])} 間")
    cols[2].metric('已列項目估算' if spending['total'] is not None else '目前部分估算',
                   f"NT$ {spending['total'] if spending['total'] is not None else spending['known_subtotal']:,.0f}")
    for warning in result.get('warnings', []):
        st.info(warning)
    if spending['total'] is None:
        st.caption('費用尚缺：' + '、'.join(spending['unknown_costs']) + '。目前數字不代表完整旅費。')
    else:
        st.caption('估算範圍為住宿、已列活動、餐食與市內交通，不含機票及跨城交通。')
    with st.expander('資料來源與查價狀態'):
        st.write(result['data_notice'])
        st.caption(result.get('spot_message', ''))
        st.caption(result.get('booking', {}).get('message', ''))
    overview, hotels, spots, costs = st.tabs(['每日行程', '住宿精選', '探索景點', '預算與建議'])
    with overview:
        st.caption('以下為行程草案；時段尚未與各景點營業日、預約名額及交通班次核對，出發前請確認。')
        rows = result['itinerary']
        if not rows:
            st.info('目前沒有取得可核實的景點。請確認地名、加上國家後重新查詢。')
        else:
            frame = pd.DataFrame(rows)
            for day, daily in frame.groupby('day', sort=True):
                with st.container(border=True):
                    st.markdown(f"### 第 {int(day):02d} 天 · {daily.iloc[0]['date']}")
                    # 卡片用原始 JSON 保留 None，避免 Pandas 將空費用轉成 NaN。
                    for row in (item for item in rows if item['day'] == day):
                        a, b = st.columns([4, 1])
                        with a:
                            fee = row.get('cost_twd_per_person')
                            card(row['spot'], row['time'], row['activity'],
                                 f'每人 NT$ {fee:,.0f}' if fee is not None else '門票／活動費待查')
                            st.caption(row.get('fee_note') or '費用資料待確認')
                            if row.get('travel_minutes_estimate'):
                                st.caption(f"至此站移動約 {row['travel_minutes_estimate']} 分鐘（座標估算）")
                        with b:
                            link('查看地圖', row.get('google_maps_url') or row.get('map_url'))
            covered = {row['day'] for row in rows}
            missing_days = sorted(set(range(1, trip.get('days', max(covered)) + 1)) - covered)
            if missing_days:
                st.warning('尚未安排第 ' + '、'.join(map(str, missing_days)) + ' 天；目前景點資料不足，請再補充行程。')
            st.caption(f'目前取得 {len(rows)} 筆景點安排，涵蓋 {len(covered)} 天；移動時間請核對實際路線。')
            with st.expander('下載行程表'):
                download = frame[['day', 'date', 'time', 'spot', 'activity', 'cost_twd_per_person', 'fee_note']].rename(columns={
                    'day':'天數','date':'日期','time':'時間','spot':'景點','activity':'活動','cost_twd_per_person':'每人費用（TWD）','fee_note':'費用說明'})
                st.download_button('下載 CSV', download.to_csv(index=False).encode('utf-8-sig'), 'travelmate-itinerary.csv', 'text/csv')
    with hotels:
        st.caption('地圖收錄不等於目前營業或有空房；Booking 搜尋結果的名稱、地址、日期與總價都須再次核對。')
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
                if hotel.get('address'):
                    st.caption(hotel['address'])
                link('查看住宿來源網站', hotel.get('website'))
                link('查看住宿位置', hotel.get('map_url'))
                hotel_url = hotel.get('booking_url')
                is_specific = bool(hotel_url and hotel_url != result.get('booking_search_url'))
                link('查看此住宿訂房頁' if is_specific else '在 Booking 查詢此住宿',
                     hotel_url if is_specific else hotel_search_url(result.get('booking_search_url'),
                         hotel['name'], result.get('area', result['destination'])))
                if not is_specific:
                    st.caption('開啟 Booking 後才取得最新搜尋結果；本站尚未確認房價、空房或是否收錄此住宿。')
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
                link('查看景點來源網站', spot.get('website'))
                st.caption('公開地圖營業時間（可能變動）：' + str(spot['opening_hours'])
                           if spot.get('opening_hours') else '營業時間尚未確認，請核對官網或地圖。')
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
