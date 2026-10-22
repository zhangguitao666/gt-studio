"""Exercise independent audio items through real stdio MCP and native getter evidence."""
import hashlib
import json
from pathlib import Path
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.compare_native_retime_media import MCPProjectClient
from scripts.verify_reference_transitions import identity, sample_pixels


def pcm(path):
    with wave.open(str(path)) as stream:
        return stream.readframes(stream.getnframes())


def main():
    evidence = ROOT/'research/transition-deletion-runtime.json'
    native = json.loads(evidence.read_text())
    workspace = ROOT/'workspace/linked-audio-acceptance'
    workspace.mkdir(parents=True, exist_ok=True)
    client = MCPProjectClient(workspace)
    cases = []
    try:
        for record in native['records']:
            case = record['case']
            client.tool('create_project', name=case['actual_timeline'], width=640, height=360, fps=24)
            clips = []
            for i, color in enumerate(('red', 'blue')):
                media = client.tool('import_media', path=str(ROOT/'workspace/transition-reference'/f'{color}.mp4'))
                clip = client.tool('append_clip', media_id=media['id'], in_frame=12, out_frame=60, start_frame=i*48)
                clips.append(clip)
            transition = client.tool('add_transition', clip_id=clips[0]['id'])
            label = case['action'] + ('-ripple' if case['ripple'] else '-normal')
            baseline = workspace/f'{label}-embedded.wav'
            client.tool('render', output=str(baseline))
            for clip in clips:
                client.tool('detach_audio', clip_id=clip['id'], linked=True)
            detached = workspace/f'{label}-detached.wav'
            client.tool('render', output=str(detached))
            assert pcm(baseline) == pcm(detached), 'Detachment changed actual PCM output'
            if case['action'] == 'clip':
                client.tool('ripple_delete' if case['ripple'] else 'delete_clip', clip_id=clips[0]['id'])
            else:
                client.tool('delete_transition', transition_id=transition['id'])
            state = client.tool('get_state')
            media_names = {m['id']:m['name'] for m in state['media']}
            actual = {'video':[], 'audio':[]}
            for track in state['timelines'][0]['tracks']:
                for clip in track['clips']:
                    actual[track['kind']].append({'kind':track['kind'], 'name':media_names[clip['media_id']], 'start':clip['start_frame'], 'duration':clip['duration_frames']})
            origin = min(c['start'] for c in case['before']['audio'])
            expected = {kind:[dict(c, start=c['start']-origin) for c in case['after'][kind]] for kind in actual}
            assert actual == expected, (actual, expected)
            remaining = workspace/f'{label}-remaining.wav'
            client.tool('render', output=str(remaining))
            expected_pcm = pcm(baseline)[48 * 2000 * 4:] if case['ripple'] else pcm(baseline)
            assert pcm(remaining) == expected_pcm, 'Actual audio disagrees with retained independent source interval'
            output = workspace/f'{label}-deleted.mov'
            client.tool('render', output=str(output))
            pixels = sample_pixels(output)
            assert len(pixels) == (48 if case['ripple'] else 96)
            if case['ripple']:
                assert all(p[2]>240 and p[0]<10 for p in pixels)
            elif case['action'] == 'clip':
                assert all(max(p)<10 for p in pixels[:48])
                assert all(p[2]>240 and p[0]<10 for p in pixels[48:])
            project = workspace/f'{label}.json'
            client.tool('save_project', path=str(project))
            cases.append({'native_timeline':case['actual_timeline'], 'operation':label, 'actual_items':actual, 'native_normalized_items':expected, 'pcm_matches_expected_independent_interval':True, 'pcm_sha256':hashlib.sha256(pcm(remaining)).hexdigest(), 'project':identity(project), 'output':identity(output), 'decoded_video_frames':len(pixels)})
        report = {'status':'passed_bounded_independent_audio_checks', 'cases':cases, 'native_getter_evidence':identity(evidence), 'public_mcp_tool_count':len(client.request('tools/list', {})['tools']), 'limitations':['Explicit detach_audio is required; default append still embeds audio.', 'Explicit groups support ripple delete on member tracks; complete linked selection, move, split, trim and speed semantics remain open.', 'PCM equality compares independent outputs before/after detach, not native rendered audio.', 'Native comparison covers saved item names, positions and durations only.'], 'full_resolve_parity':False}
        (ROOT/'research/linked-audio-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'], 'native_cases':len(cases), 'public_tools':report['public_mcp_tool_count']}))
    finally:
        client.close()

if __name__ == '__main__':
    main()
