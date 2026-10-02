"""使用 Streamlit 真正的執行引擎驗證使用者操作，外部網路以固定回應隔離。"""
from pathlib import Path
import sys
from copy import deepcopy

import httpx
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'frontend'))


def sample_result():
    """包含未知費用、免費景點及長天數，覆蓋先前容易遺漏的混合資料。"""
    from tools.travel_tools import budget_tool
    rows = [{'day': 1, 'date': '2026-10-03', 'time': '09:00', 'spot': '真實測試景點',
             'activity': '參觀', 'cost_twd_per_person': None, 'fee_note': '門票待確認',
             'travel_minutes_estimate': None, 'map_url': 'https://www.openstreetmap.org/node/1'},
            {'day': 1, 'date': '2026-10-03', 'time': '13:30', 'spot': '免費測試景點',
             'activity': '參觀', 'cost_twd_per_person': 0, 'fee_note': '來源標示免費，請現場確認',
             'travel_minutes_estimate': 15, 'map_url': 'https://www.openstreetmap.org/node/2'}]
    hotel = {'name': '測試住宿', 'price': None, 'room_size': 25, 'room_type': '待查'}
    return {'destination': '台北', 'area': '台北市', 'itinerary': rows,
            'hotels': [hotel], 'spots': [{'name': '真實測試景點', 'category': 'museum',
            'rating': None, 'cost_twd_per_person': None}],
            'trip': {'start_date': '2026-10-03', 'days': 14, 'people': 2,
                     'budget_twd': 30000, 'preference': '文化'},
            'generated_at': '2026-10-02T01:00:00+00:00',
            'spending': budget_tool(14, 2, hotel, rows, 30000), 'data_notice': '公開資料',
            'booking_search_url': 'https://www.booking.com/searchresults.zh-tw.html?ss=Taipei',
            'advice': {'text': '請核對交通', 'source': '規則式建議', 'status': 'unconfigured'},
            'external': {}, 'tool_trace': ['hotel_tool'], 'rag_sources': []}


@pytest.fixture
def frontend(monkeypatch):
    st.cache_data.clear()
    def fake_request(self, method, url, **kwargs):
        payload = sample_result() if method == 'POST' else {'status': 'ok', 'configured': False}
        return httpx.Response(200, json=payload, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx.Client, 'request', fake_request)
    return AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'frontend/app.py'))


def test_card_results_preserve_unknown_prices_and_search_link(frontend):
    frontend.session_state['plan_result'] = sample_result()
    frontend.run(timeout=30)
    assert not frontend.exception
    rendered = ' '.join(item.value for item in frontend.markdown)
    assert 'nan' not in rendered.lower()
    assert '門票／活動費待查' in rendered
    assert '每人 NT$ 0' in rendered
    assert any('約 7.6 坪' in c.value for c in frontend.caption)
    assert any('尚未安排第 2' in w.value for w in frontend.warning)
    assert any('搜尋目的地住宿與房價' in b.label for b in frontend.get('link_button'))


def test_empty_results_and_stale_results_cleared_on_blank_input(frontend):
    body = sample_result()
    body.update(itinerary=[], hotels=[], spots=[])
    frontend.session_state['plan_result'] = body
    frontend.run(timeout=30)
    assert not frontend.exception
    assert any('目前沒有取得' in i.value for i in frontend.info)
    frontend.text_input[0].set_value('   ')
    next(b for b in frontend.button if b.label == '開始規劃旅程').click()
    frontend.run(timeout=30)
    assert not frontend.exception
    assert any('請先輸入目的地' in e.value for e in frontend.error)
    assert 'plan_result' not in frontend.session_state


def test_timeout_does_not_leave_old_itinerary(frontend, monkeypatch):
    frontend.session_state['plan_result'] = sample_result()
    frontend.run(timeout=30)
    def failed_request(self, method, url, **kwargs):
        raise httpx.ReadTimeout('private diagnostic details')
    monkeypatch.setattr(httpx.Client, 'request', failed_request)
    next(b for b in frontend.button if b.label == '開始規劃旅程').click()
    frontend.run(timeout=30)
    assert not frontend.exception
    assert 'plan_result' not in frontend.session_state
    assert any('連線逾時' in e.value for e in frontend.error)
    assert not any('private diagnostic' in e.value for e in frontend.error)


def test_google_spots_do_not_make_advice_claim_empty_itinerary():
    from services.llm import _fallback
    facts = {'destination':'東京', 'days':3, 'has_verified_spots':True, 'spots':[],
             'hotel':None, 'spending':sample_result()['spending']}
    assert '沒有取得可核實' not in _fallback(facts)


def test_budget_does_not_claim_complete_when_trip_days_are_missing():
    from tools.travel_tools import budget_tool
    incomplete = budget_tool(14, 2, {'price':2000}, [{'day':1,'cost_twd_per_person':0}], 100000)
    assert incomplete['total'] is None
    assert '景點／活動' in incomplete['unknown_costs']
    complete = budget_tool(2, 2, {'price':2000}, [
        {'day':1,'cost_twd_per_person':0}, {'day':2,'cost_twd_per_person':0}], 100000)
    assert complete['total'] == 7000
