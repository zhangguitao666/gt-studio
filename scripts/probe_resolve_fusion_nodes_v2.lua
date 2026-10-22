-- Dedicated REA reference project only; creates new synthetic timelines and render jobs.
local expected='REA Reference · 2026-10-21'
local media_path='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-native-reference/source640.mov'
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
assert(project and project:GetName()==expected,'Wrong reference project')
assert(not project:IsRenderingInProgress(),'Reference project is rendering')
local pool=project:GetMediaPool();local imported=pool:ImportMedia({media_path});assert(imported and imported[1],'Synthetic source import failed')
local stamp=os.date('%Y%m%d_%H%M%S')
local output='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-native-reference'
local jobs={}
local codec=nil
for _,label in pairs(project:GetRenderCodecs('mov')) do
 if type(label)=='string' and label:lower():find('prores') and label:lower():find('hq') and not label:find('4444') then codec=label end
end
assert(codec,'No ProRes HQ codec')
assert(project:SetCurrentRenderFormatAndCodec('mov',codec),'Cannot select ProRes')
assert(project:SetCurrentRenderMode(1),'Cannot select single-clip mode')
REA_FUSION_NATIVE_REPORT={stamp=stamp,rows={},job_ids=jobs}
local modes={'identity','background_half','transform_upper_right','merge_half','rotation_90','fanout'}
for _,mode in ipairs(modes) do
 local timeline=pool:CreateEmptyTimeline('REA_FUSION_'..stamp..'_'..mode)
 assert(timeline and project:SetCurrentTimeline(timeline),'Could not create dedicated timeline')
 local row={after={mode=mode,version=resolve:GetVersionString(),captured_at_utc=os.date('!%Y-%m-%dT%H:%M:%SZ'),source=media_path,operations={},nodes={}},timeline=timeline:GetName(),completed=false}
 local a=row.after
 local function operation(label,fn)
  local ok,value=pcall(fn);local record={label=label,ok=ok};if ok then record.value=value else record.error=tostring(value) end;a.operations[#a.operations+1]=record
  assert(ok and value~=false,label..': '..tostring(value));return value
 end
 local ok,reason=pcall(function()
  a.timeline_origin=timeline:GetStartFrame()
  a.custom_settings=timeline:SetSetting('useCustomSettings','1')
  a.width_setting=timeline:SetSetting('timelineResolutionWidth','640')
  a.height_setting=timeline:SetSetting('timelineResolutionHeight','360')
  assert(a.custom_settings and a.width_setting and a.height_setting,'Timeline settings rejected')
  pool:AppendToTimeline({{mediaPoolItem=imported[1],startFrame=0,endFrame=48,recordFrame=a.timeline_origin,trackIndex=1}})
  local clip=timeline:GetItemListInTrack('video',1)[1];assert(clip,'Video clip absent')
  a.clip_properties=clip:GetProperty()
  a.project_color={}
  for _,key in ipairs({'colorScienceMode','colorManagementPreset','timelineColorSpace','timelineGamma','outputColorSpace','outputGamma','inputColorSpace','inputGamma','isAutoColorManage'}) do a.project_color[key]=project:GetSetting(key) end
  a.clip={id=clip:GetUniqueId(),start=clip:GetStart(true),duration=clip:GetDuration(true),source_start=clip:GetSourceStartFrame(),source_end=clip:GetSourceEndFrame()}
  local comp=operation('AddFusionComp',function()return clip:AddFusionComp()end);assert(comp,'No Fusion composition returned')
  a.comp_count=clip:GetFusionCompCount();a.comp_names=clip:GetFusionCompNameList()
  a.frame_format={width=comp:GetPrefs('Comp.FrameFormat.Width'),height=comp:GetPrefs('Comp.FrameFormat.Height'),rate=comp:GetPrefs('Comp.FrameFormat.Rate')}
  local function find(kind)
   for _,node in pairs(comp:GetToolList(false,kind)) do return node end
  end
  local media_in=find('MediaIn');local media_out=find('MediaOut');assert(media_in and media_out,'Default media nodes absent')
  local function node(kind)
   local created=operation('AddTool '..kind,function()return comp:AddTool(kind)end);assert(created,'Missing '..kind);return created
  end
  local function set(n,key,value)
   operation('SetInput '..key,function()return n:SetInput(key,value)end)
   local read=n:GetInput(key)
   if type(value)=='number' then assert(type(read)=='number' and math.abs(read-value)<.00001,'Input readback differs: '..key) end
   return read
  end
  local function connect(n,port,source)
   operation('ConnectInput '..port,function()return n:ConnectInput(port,source)end)
  end
  if mode~='identity' then
   local bg=node('Background');set(bg,'UseFrameFormatSettings',0);set(bg,'Width',640);set(bg,'Height',360)
   set(bg,'TopLeftRed',0);set(bg,'TopLeftGreen',0);set(bg,'TopLeftBlue',1);set(bg,'TopLeftAlpha',mode=='rotation_90' and 1 or .5)
   local target=bg
   if mode=='transform_upper_right' or mode=='merge_half' or mode=='rotation_90' then
    local tr=node('Transform');set(tr,'Size',.5);set(tr,'Center',{.75,.75});connect(tr,'Input',bg);target=tr
   end
   if mode=='merge_half' then
    local merge=node('Merge');set(merge,'Blend',.5);connect(merge,'Background',media_in);connect(merge,'Foreground',target);target=merge
   elseif mode=='fanout' then
    local merge=node('Merge');set(merge,'Blend',1);connect(merge,'Background',bg);connect(merge,'Foreground',bg);target=merge
   elseif mode=='rotation_90' then
    local rot=node('Transform');set(rot,'Angle',90);connect(rot,'Input',target);target=rot
   end
   connect(media_out,'Input',target)
  end
  for _,n in pairs(comp:GetToolList(false)) do
   local attrs=n:GetAttrs();local record={name=attrs.TOOLS_Name,class=attrs.TOOLS_RegID,inputs={}}
   for _,key in ipairs({'Width','Height','UseFrameFormatSettings','TopLeftRed','TopLeftGreen','TopLeftBlue','TopLeftAlpha','Center','Size','Angle','Blend'}) do
    local good,value=pcall(function()return n:GetInput(key)end)
    if good and value~=nil then record.inputs[key]=value end
   end
   for key,input in pairs(n:GetInputList() or {}) do
    local good,link=pcall(function()return input:GetConnectedOutput()end)
    if good and link then
     local owner=link:GetTool();local oa=owner and owner:GetAttrs() or {};local ia=input:GetAttrs()
     record.inputs[ia.INPS_ID or tostring(key)]={source_op=oa.TOOLS_Name,source_port=(link:GetAttrs() or {}).OUTS_ID}
    end
   end
   a.nodes[#a.nodes+1]=record
  end
  a.timeline_settings={width=timeline:GetSetting('timelineResolutionWidth'),height=timeline:GetSetting('timelineResolutionHeight'),fps=timeline:GetSetting('timelineFrameRate')}
  local settings={SelectAllFrames=true,TargetDir=output,CustomName=timeline:GetName(),ExportVideo=true,ExportAudio=true,FormatWidth=640,FormatHeight=360,FrameRate=24,AudioCodec='lpcm',AudioBitDepth=24,AudioSampleRate=48000,ExportSubtitle=false}
  assert(project:SetRenderSettings(settings),'Render settings rejected');a.render_settings=settings
  local id=project:AddRenderJob();assert(id and id~='','Could not add render job');a.job_id=id;jobs[#jobs+1]=id
  row.completed=true
 end)
 if not ok then a.error=tostring(reason) end
 assert(timeline:AddMarker(0,ok and 'Green' or 'Red','REA_FUSION_NODE_EVIDENCE',json(row),1,json(row)),'Could not retain evidence marker')
 manager:SaveProject();REA_FUSION_NATIVE_REPORT.rows[#REA_FUSION_NATIVE_REPORT.rows+1]=row
 print('REA_FUSION_NODE_EVIDENCE='..json(row))
end
if #jobs>0 then
 REA_FUSION_NATIVE_REPORT.started=project:StartRendering(jobs,false)
 local timeline=project:GetCurrentTimeline();local launch={after={job_ids=jobs,started=REA_FUSION_NATIVE_REPORT.started,queue=project:GetRenderJobList(),stamp=stamp},timeline=timeline:GetName(),completed=true}
 timeline:AddMarker(1,'Blue','REA_FUSION_RENDER_LAUNCH',json(launch),1,json(launch));manager:SaveProject()
end
resolve:OpenPage('edit')
