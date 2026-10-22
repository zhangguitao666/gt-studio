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
assert(not project:IsRenderingInProgress(),'Rendering already active')
local pool=project:GetMediaPool()
local red=pool:ImportMedia({'/Users/zgt/agent/resolve-reconstruction/workspace/transition-reference/red.mp4'})[1]
local blue=pool:ImportMedia({'/Users/zgt/agent/resolve-reconstruction/workspace/transition-reference/blue.mp4'})[1]
assert(red and blue,'Source imports failed')
local function attempt(fn)
 local ok,value=pcall(fn)
 return {success=ok,value=ok and value or nil,error=not ok and tostring(value) or nil}
end
local function metrics(item)
 if not item then return {missing=true} end
 return {kind=item:GetType(),name=item:GetName(),start=item:GetStart(true),finish=item:GetEnd(true),duration=item:GetDuration(true),source_start=attempt(function()return item:GetSourceStartFrame()end),source_end=attempt(function()return item:GetSourceEndFrame()end),properties=attempt(function()return item:GetProperties()end)}
end
assert(project:SetCurrentRenderFormatAndCodec('mov','ProRes422HQ'),'Codec rejected')
assert(project:SetCurrentRenderMode(1),'Single clip mode rejected')
local specs={{'center12','center',12,12,60,'end'},{'left12','left',12,12,60,'end'},{'right12','right',12,12,60,'end'},{'center11','center',11,12,60,'end'},{'nohandles','center',12,0,72,'end'},{'startcenter12','center',12,12,60,'start'}}
REA_TRANSITION_REPORT={after={version=r:GetVersionString(),cases={}},timeline='REA_TRANSITION_BATCH',completed=true}
local ids={}
local stamp=os.date('%Y%m%d_%H%M%S')
for _,spec in ipairs(specs) do
 local row={after={},timeline='REA_DISSOLVE_'..stamp..'_'..spec[1],completed=false,alignment=spec[2],duration=spec[3],in_frame=spec[4],out_frame=spec[5],position=spec[6]}
 local timeline=pool:CreateEmptyTimeline(row.timeline)
 assert(timeline and project:SetCurrentTimeline(timeline),'Timeline creation failed')
 local ok,reason=pcall(function()
  local origin=timeline:GetStartFrame()
  pool:AppendToTimeline({{mediaPoolItem=red,startFrame=spec[4],endFrame=spec[5],recordFrame=origin,trackIndex=1}})
  local first=timeline:GetItemListInTrack('video',1)[1]
  pool:AppendToTimeline({{mediaPoolItem=blue,startFrame=spec[4],endFrame=spec[5],recordFrame=first:GetEnd(true),trackIndex=1}})
  local items=timeline:GetItemListInTrack('video',1)
  assert(items and #items==2,'Need exactly two clips')
  table.sort(items,function(a,b)return a:GetStart(true)<b:GetStart(true)end)
  row.before={first=metrics(items[1]),second=metrics(items[2]),origin=origin}
  local target=spec[6]=='start' and items[2] or items[1]
  local transition=target:AddTransition({type='Cross Dissolve',category='simple',position=spec[6],alignment=spec[2],duration=spec[3]})
  row.after.add_returned_item=transition~=nil
  row.after.transition=metrics(transition)
  row.after.first=metrics(items[1]);row.after.second=metrics(items[2])
  row.after.items={}
  for _,item in ipairs(timeline:GetItemListInTrack('video',1)) do row.after.items[#row.after.items+1]=metrics(item) end
  row.after.finish=timeline:GetEndFrame()
  assert(project:SetRenderSettings({SelectAllFrames=true,TargetDir='/Users/zgt/agent/resolve-reconstruction/workspace/transition-reference/native-v1',CustomName=row.timeline,ExportVideo=true,ExportAudio=true,FormatWidth=640,FormatHeight=360,FrameRate=24,AudioCodec='lpcm',AudioBitDepth=24,AudioSampleRate=48000}),'Render settings rejected')
  row.after.job_id=project:AddRenderJob();assert(row.after.job_id,'No render job')
  ids[#ids+1]=row.after.job_id
 end)
 row.completed=ok;if not ok then row.after.error=tostring(reason) end
 timeline:AddMarker(0,'Blue','REA_TRANSITION_EVIDENCE',json(row),1,json(row))
 REA_TRANSITION_REPORT.after.cases[#REA_TRANSITION_REPORT.after.cases+1]=row
 print('REA_TRANSITION_CASE='..json(row))
end
assert(manager:SaveProject(),'Reference save failed')
if #ids>0 then project:StartRendering(ids,false) end
