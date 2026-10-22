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
assert(project and project:GetName()==expected,'Current project is not the dedicated REA reference project; stopped')
REA_RETIME_REPORT={schema_version=2,captured_at_utc=os.date('!%Y-%m-%dT%H:%M:%SZ'),version=r:GetVersionString(),project=project:GetName(),source=media_path,cases={}}
local report=REA_RETIME_REPORT
local function attempt(fn)
 local ok,value=pcall(fn)
 if not ok then return {error=tostring(value),success=false} end
 return {success=true,value=value,returned_nil=value==nil}
end
report.set_project_rate=attempt(function()return project:SetSettings({timelineFrameRate='24'})end)
report.project_rate=project:GetSettings().timelineFrameRate
local pool=project:GetMediaPool()
local imported=pool:ImportMedia({{FilePath=media_path}})
report.import_observation=imported
print('REA_IMPORT_TYPED='..json(imported))
if not imported or not imported[1] then
 imported=pool:ImportMedia({media_path})
 report.import_string_observation=imported
 print('REA_IMPORT_STRINGS='..json(imported))
end
if not imported or not imported[1] then
 imported=r:GetMediaStorage():AddItemListToMediaPool({media_path})
 report.storage_import_observation=imported
 print('REA_IMPORT_STORAGE='..json(imported))
end
assert(imported and imported[1],'Generated reference media import failed')
local source=imported[1]
report.source_rate=source:GetClipProperty('FPS')
local function metrics(item)
 if not item then return {missing=true} end
 return {start=item:GetStart(true),finish=item:GetEnd(true),duration=item:GetDuration(true),
 source_start=item:GetSourceStartFrame(),source_end=item:GetSourceEndFrame(),speed=item:GetSpeed()}
end
local stamp=os.date('%Y%m%d_%H%M%S')
for _,spec in ipairs({{100,false},{200,false},{50,false},{200,true},{50,true},{-100,false},{0,false}}) do
 local row={percentage=spec[1],ripple=spec[2]}
 local ok,reason=pcall(function()
  local name='REA_SPEED_'..stamp..'_'..tostring(spec[1])..'_'..tostring(spec[2])
  -- Separate explicit placements avoid duplicate-source collapse/overlap in
  -- CreateTimelineFromClips. Read actual duration; do not assume end semantics.
  local timeline=pool:CreateEmptyTimeline(name)
  assert(timeline,'Could not create reference timeline')
  assert(project:SetCurrentTimeline(timeline),'Could not select reference timeline')
  row.timeline=name;row.timeline_rate=timeline:GetSettings().timelineFrameRate
  local origin=timeline:GetStartFrame()
  row.first_append=attempt(function()
   return #pool:AppendToTimeline({{mediaPoolItem=source,startFrame=0,endFrame=47,recordFrame=origin,trackIndex=1}})
  end)
  local first_items=timeline:GetItemListInTrack('video',1)
  assert(first_items and #first_items==1,'First append did not produce one video clip')
  local boundary=first_items[1]:GetEnd(true)
  row.second_append=attempt(function()
   return #pool:AppendToTimeline({{mediaPoolItem=source,startFrame=0,endFrame=47,recordFrame=boundary,trackIndex=1}})
  end)
  local items=timeline:GetItemListInTrack('video',1)
  assert(items and #items==2,'Expected exactly two generated video clips')
  table.sort(items,function(a,b)return a:GetStart(true)<b:GetStart(true)end)
  assert(items[1]:GetEnd(true)==items[2]:GetStart(true),'Generated clips are not adjacent')
  row.before={first=metrics(items[1]),second=metrics(items[2])}
  row.set_speed=attempt(function()return items[1]:SetSpeed({Percentage=spec[1],PitchCorrection=true,RippleTimeline=spec[2],StretchKeyframesToFit=false})end)
  row.after={first=metrics(items[1]),second=metrics(items[2])}
 end)
 row.completed=ok
 if not ok then row.error=tostring(reason) end
 report.cases[#report.cases+1]=row
 -- Persist raw case JSON in our new timeline, without needing the Console's
 -- absent io global or changing scripting/security preferences.
 if row.timeline then
  row.evidence_marker=attempt(function()
   return project:GetCurrentTimeline():AddMarker(0,'Blue','REA_RETIME_EVIDENCE',json(row),1,json(row))
  end)
 end
 print('REA_RETIME_CASE='..json(row))
end
report.save_project=attempt(function()return manager:SaveProject()end)
print('REA_RETIME_META='..json({captured_at_utc=report.captured_at_utc,version=report.version,project=report.project,source=report.source,project_rate=report.project_rate,source_rate=report.source_rate,set_project_rate=report.set_project_rate,case_count=#report.cases}))
