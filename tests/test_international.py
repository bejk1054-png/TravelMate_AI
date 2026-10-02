"""國際地名、停用地點及住宿分類回歸；不冒稱線上庫存測試。"""
from services.places import _belongs_to_area, _unavailable, _lodging_candidate
from services.location import city_search_name


def test_international_addresses():
    """跨國同名不得混入，行政區別名與重音可以正確比對。"""
    assert _belongs_to_area({'display_name':'Hotel, Westminster, Greater London, UK',
                             'address':{'country_code':'gb'}}, 'London, GB')
    assert not _belongs_to_area({'display_name':'Hotel, Paris, Texas',
                                 'address':{'country_code':'us'}}, 'Paris, FR')
    assert _belongs_to_area({'display_name':'Museum, São Paulo, Brazil',
                             'address':{'country_code':'br'}}, 'Sao Paulo, BR')
    assert not _belongs_to_area({'name':'Unknown'}, 'Tokyo, JP')
    assert city_search_name('奈洛比') == 'Nairobi'


def test_closed_places_and_pub_are_not_recommended():
    """已關閉景點和無房間佐證的酒吧必須排除。"""
    assert _unavailable({'extratags':{'opening_hours':'closed "Closed for renovations"'}})
    assert not _unavailable({'extratags':{'opening_hours':'Mo off; Tu-Su 10:00-18:00'}})
    assert not _lodging_candidate({'extratags':{'bar':'yes'}})
    assert _lodging_candidate({'extratags':{'bar':'yes','rooms':'20'}})
