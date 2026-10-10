"""Two official tools using one SearchMesh run. Start the gateway first."""
import os
from concurrent.futures import ThreadPoolExecutor
from serpapi_search_tools import SearchResultFormat, web_search
from searchmesh.client import SearchMeshClient


def main():
    settings = {
        "gateway_url": os.getenv("SEARCHMESH_GATEWAY_URL", "http://127.0.0.1:8001"),
        "token": os.environ["SEARCHMESH_GATEWAY_TOKEN"],
        "deadline_seconds": 120,
        "max_age_seconds": 300,
    }
    owner = SearchMeshClient(**settings, agent_id="run-owner")
    run = owner.create_run("Custom-client integration example", budget_limit=10)

    def worker(agent_id):
        client = SearchMeshClient(**settings, run_id=run["id"], agent_id=agent_id)
        search = web_search(provider="function", client=client, response_format=SearchResultFormat.JSON)
        return agent_id, search(query="specialty coffee shops HSR Layout Bengaluru")

    print("Run:", run["id"])
    # Deliberately identical calls illustrate the integration contract.
    with ThreadPoolExecutor(max_workers=2) as pool:
        for agent_id, result in pool.map(worker, ["researcher", "reviewer"]):
            print(agent_id, result)


if __name__ == "__main__":
    main()
