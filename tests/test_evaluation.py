from searchmesh.evaluation import evaluate


def test_trace_evaluation_preserves_queries():
    trace={'run':{'id':'captured'},'requests':[
        {'agent_id':'compatibility_researcher','params':{'engine':'google_light','q':'Python 3.13 NumPy'}},
        {'agent_id':'platform_researcher','params':{'engine':'google_light','q':'Python 3.13 NumPy'}},
        {'agent_id':'verifier','params':{'engine':'google_light','q':'Python 3.13 NumPy free-threaded'}}]}
    report=evaluate(trace,iterations=1)
    assert report['requests_per_trial']==3
    by_name={row['baseline']:row for row in report['samples']}
    assert by_name['Direct']['provider_attempts']==3
    assert by_name['SearchMesh']['provider_attempts']==2
    for row in report['samples']:
        assert row['failures']==0
        assert sorted(x['params']['q'] for x in row['requests'])==sorted(x['params']['q'] for x in trace['requests'])
