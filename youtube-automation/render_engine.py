from visual_engine import get_visuals

def render(script):
    print("\n🎬 RENDER START")

    for s in script["segments"]:
        visuals = get_visuals()

        print(f"""
CUT {s['t']}
EMOTION: {s['emotion']}
VISUALS: {visuals}
STYLE: faceless cinematic, teal/orange, slow zoom
CUT TYPE: {s['cut']}
""")

    print("\n✅ RENDER COMPLETE")
