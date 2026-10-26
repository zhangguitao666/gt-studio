-- Guarded synthetic audio gain and overload experiment.
local function quote(s)
 return '"'..tostring(s):gsub('[%z\1-\31\\"]',function(c)
  return ({['"']='\\"',['\\']='\\\\',['\n']='\\n',['\r']='\\r',['\t']='\\t'})[c] or string.format('\\u%04x',string.byte(c))
 end)..'"'
end
local function json(x)
 local t=type(x)
 if t=='nil' then return 'null' end
 if t=='string' then return quote(x) end
 if t=='boolean' or t=='number' then return tostring(x) end
 if t~='table' then return quote('<'..t..'>') end
 local keys={};for k,_ in pairs(x) do keys[#keys+1]=k end
 local array=#keys>0
 for _,k in ipairs(keys) do if type(k)~='number' then array=false end end
 local out={}
 if array then for i=1,#x do out[#out+1]=json(x[i]) end;return '['..table.concat(out,',')..']' end
 table.sort(keys,function(a,b)return tostring(a)<tostring(b)end)
 for _,k in ipairs(keys) do out[#out+1]=quote(k)..':'..json(x[k]) end
 return '{'..table.concat(out,',')..'}'
end
local manager=resolve:GetProjectManager();local project=manager:GetCurrentProject()
assert(project and project:GetName()=='REA Reference · 2026-10-21','Wrong reference project')
assert(not project:IsRenderingInProgress(),'Reference render active')
local root='/Users/zgt/agent/resolve-reconstruction/workspace/audio-gain-native'
local pool=project:GetMediaPool();local sources={}
for _,name in ipairs({'dc','negative','sine'}) do local m=pool:ImportMedia({root..'/'..name..'.wav'});assert(m and m[1]);sources[name]=m[1] end
local prefix='REA_AUDIO_GAIN_'..os.date('%Y%m%d_%H%M%S')..'_';local ids={};local codec
local codecs=project:GetRenderCodecs('mov') or {}
for _,label in pairs(codecs) do if type(label)=='string' and label:lower():find('prores') and label:lower():find('hq') and not label:find('4444') then codec=label end end
local cases={
 {name='dc_unity',items={{track=1,source='dc',gain=0,start=0}}},
 {name='dc_minus6',items={{track=1,source='dc',gain=-6,start=0}}},
 {name='dc_plus6',items={{track=1,source='dc',gain=6,start=0}}},
 {name='negative_plus6',items={{track=1,source='negative',gain=6,start=0}}},
 {name='sine_plus6',items={{track=1,source='sine',gain=6,start=0}}},
 {name='dc_overlap',items={{track=1,source='dc',gain=0,start=0},{track=2,source='dc',gain=0,start=0}}},
 {name='dc_cancel',items={{track=1,source='dc',gain=0,start=0},{track=2,source='negative',gain=0,start=0}}},
 {name='dc_stagger',items={{track=1,source='dc',gain=0,start=0},{track=2,source='dc',gain=0,start=12}}}
}
REA_AUDIO_GAIN_REPORT={prefix=prefix,ids=ids,rows={}}
for _,case in ipairs(cases) do
 local t=pool:CreateEmptyTimeline(prefix..case.name);assert(t and project:SetCurrentTimeline(t))
 local row={after={audio_gain=true,attempt=2,output_format='mov_audio_only_pcm24',prefix=prefix,case=case,version=resolve:GetVersionString(),mov_codecs=codecs,jobs={},clips={}},timeline=t:GetName(),completed=false}
 local a=row.after
 local ok,reason=pcall(function()
  assert(codec,'Known MOV codec unavailable');assert(project:SetCurrentRenderMode(1));assert(project:SetCurrentRenderFormatAndCodec('mov',codec))
  if #case.items>1 then assert(t:AddTrack('audio','stereo')) end
  local origin=t:GetStartFrame();a.origin=origin;a.fps=t:GetSetting('timelineFrameRate')
  for _,item in ipairs(case.items) do
   local clips=pool:AppendToTimeline({{mediaPoolItem=sources[item.source],startFrame=0,endFrame=48,recordFrame=origin+item.start,trackIndex=item.track,mediaType=2}})
   assert(clips and clips[1],'Audio-only append failed');assert(clips[1]:SetProperty('AudioVolume',item.gain),'AudioVolume rejected')
  end
  for i=1,t:GetTrackCount('audio') do
   for _,clip in ipairs(t:GetItemListInTrack('audio',i)) do
    a.clips[#a.clips+1]={track=i,start=clip:GetStart(true),duration=clip:GetDuration(true),['end']=clip:GetEnd(true),properties=clip:GetProperty()}
   end
  end
  a.end_frame=t:GetEndFrame();local settings={SelectAllFrames=true,TargetDir=root,CustomName=t:GetName(),ExportVideo=false,ExportAudio=true,AudioCodec='lpcm',AudioBitDepth=24,AudioSampleRate=48000}
  assert(project:SetRenderSettings(settings),'Audio settings rejected');local id=project:AddRenderJob();assert(id and id~='');a.jobs[#a.jobs+1]={id=id,codec=codec,settings=settings};ids[#ids+1]=id;row.completed=true
 end)
 if not ok then a.error=tostring(reason) end
 assert(t:AddMarker(0,ok and 'Green' or 'Red','REA_AUDIO_GAIN_EVIDENCE',json(row),1,json(row)));manager:SaveProject();REA_AUDIO_GAIN_REPORT.rows[#REA_AUDIO_GAIN_REPORT.rows+1]=row
 print('REA_AUDIO_GAIN_EVIDENCE='..json(row))
end
if #ids>0 then
 local started=project:StartRendering(ids,false);local t=project:GetCurrentTimeline();local row={after={audio_gain_launch=true,prefix=prefix,ids=ids,started=started},timeline=t:GetName(),completed=true};assert(t:AddMarker(1,'Blue','REA_AUDIO_GAIN_LAUNCH',json(row),1,json(row)));manager:SaveProject()
end
resolve:OpenPage('edit')
