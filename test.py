from src.batchParser import load, dump


with open("bat", encoding="utf-8") as fp:
    for obj in load(fp):
        print(obj.json)
