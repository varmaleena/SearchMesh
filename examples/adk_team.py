"""Run from the installed project: python examples/adk_team.py"""
import asyncio
import os
from searchmesh.adk_demo import run_live

if __name__=="__main__":
    asyncio.run(run_live("http://127.0.0.1:8000",os.getenv("SEARCHMESH_GATEWAY_TOKEN","")))

