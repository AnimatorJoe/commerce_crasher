import yaml

def writeRuntimeState(state: list, output_path: str):
    with open(output_path, "a", encoding="utf-8") as file:
        yaml.dump(state, file, allow_unicode=True)
        
        
def createVisualizationFrom(source_path: str, output_path: str):
    data = yaml.safe_load(open(source_path, "r"))
    with open(output_path, "w", encoding="utf-8") as file:
        file.write() 