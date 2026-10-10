from serpapi_search_tools import web_search,news_search,SearchResultFormat


def test_real_package_uses_custom_client():
    class Recording:
        def __init__(self):self.params=None
        def search(self,params):
            self.params=params
            return {'search_metadata':{'status':'Success'},'organic_results':[{'title':'Synthetic','link':'https://example.org','snippet':'Fixture'}]}
    c=Recording()
    tool=web_search(provider='function',client=c,response_format=SearchResultFormat.JSON)
    result=tool(query='exact version compatibility')
    assert c.params['q']=='exact version compatibility'
    assert 'api_key' not in c.params
    assert 'Synthetic' in result


def test_news_contract():
    class Recording:
        def search(self,params):
            assert params['engine']=='google_news'
            return {'news_results':[{'title':'Fixture news','link':'https://example.org'}]}
    tool=news_search(provider='function',client=Recording(),response_format=SearchResultFormat.JSON)
    assert 'Fixture news' in tool(query='test news')
