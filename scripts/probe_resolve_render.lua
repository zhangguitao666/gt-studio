-- Scope: generated media and newly-created timelines in the dedicated reference project only.
-- No preference changes, original media writes or user timeline edits.
local expected='REA Reference · 2026-10-21'
local media_path='/Users/zgt/agent/resolve-reconstruction/workspace/demo-media/motion.mp4'
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
local r=resolve
local manager=r:GetProjectManager()
local project=manager:GetCurrentProject()
assert(project and project:GetName()==expected,'Wrong reference project')
assert(not project:IsRenderingInProgress(),'A render is already running; stopped')
local diagnostic={after={version=r:GetVersionString()},timeline='REA_RENDER_DIAGNOSTIC',completed=false}
local ok,reason=pcall(function()
local wanted={["REA_SPEED_20261021_143001_-100_false"]=true,["REA_SPEED_20261021_143001_0_false"]=true,["REA_SPEED_20261021_143001_100_false"]=true,["REA_SPEED_20261021_143001_200_false"]=true,["REA_SPEED_20261021_143001_200_true"]=true,["REA_SPEED_20261021_143001_50_false"]=true,["REA_SPEED_20261021_143001_50_true"]=true,["REA_FREEZE_20261021_143926_0"]=true,["REA_FREEZE_20261021_143926_12"]=true,["REA_FREEZE_20261021_143926_46"]=true}
local output="/Users/zgt/agent/resolve-reconstruction/workspace/native-render-20261021-v2"
local timelines={}
for i=1,project:GetTimelineCount() do
 local timeline=project:GetTimelineByIndex(i)
 if wanted[timeline:GetName()] then timelines[timeline:GetName()]=timeline end
end
local count=0;for _ in pairs(timelines) do count=count+1 end
assert(count==10,'Expected exactly ten existing reference timelines')
local codecs=project:GetRenderCodecs('mov')
diagnostic.after.codecs=codecs
local codec=nil
for key,label in pairs(codecs) do
 if type(label)=='string' and label:lower():find('prores') and label:lower():find('hq') and not label:find('4444') then codec=label end
end
assert(codec,'No ProRes HQ encoder observed')
assert(project:SetCurrentRenderFormatAndCodec('mov',codec),'Could not set MOV ProRes codec')
assert(project:SetCurrentRenderMode(1),'Could not choose single clip')
REA_RENDER_REPORT={after={captured_at_utc=os.date('!%Y-%m-%dT%H:%M:%SZ'),version=r:GetVersionString(),codec=codec,output=output,jobs={}},timeline='REA_RENDER_BATCH',completed=false}
local report=REA_RENDER_REPORT
local ids={}
for name,timeline in pairs(timelines) do
 assert(project:SetCurrentTimeline(timeline),'Could not select timeline')
 local settings={SelectAllFrames=true,TargetDir=output,CustomName=name,ExportVideo=true,ExportAudio=true,FormatWidth=640,FormatHeight=360,FrameRate=24,AudioCodec='lpcm',AudioBitDepth=24,AudioSampleRate=48000,ExportSubtitle=false}
 assert(project:SetRenderSettings(settings),'Render settings rejected')
 local id=project:AddRenderJob()
 assert(id and id~='','Render job not created')
 ids[#ids+1]=id
 report.after.jobs[#report.after.jobs+1]={id=id,timeline=name,settings=settings,start=timeline:GetStartFrame(),finish=timeline:GetEndFrame()}
end
report.completed=true
report.after.start_result=project:StartRendering(ids,false)
report.after.queue=project:GetRenderJobList()
local current=project:GetCurrentTimeline()
report.after.marker_saved=current:AddMarker(6,'Green','REA_RENDER_EVIDENCE',json(report),1,json(report))
manager:SaveProject()
print('REA_RENDER_BATCH='..json(report))

end)
diagnostic.completed=ok
if not ok then diagnostic.after.error=tostring(reason) end
local current=project:GetCurrentTimeline()
current:AddMarker(5,'Yellow','REA_RENDER_DIAGNOSTIC',json(diagnostic),1,json(diagnostic))
manager:SaveProject()
print('REA_RENDER_DIAGNOSTIC='..json(diagnostic))
