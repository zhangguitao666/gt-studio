-- Guarded synthetic Alpha/Blend and lower-track experiment.
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
local source='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-native-reference/source640.mov'
local output='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-alpha-ramp-native'
local pool=project:GetMediaPool();local media=pool:ImportMedia({source});assert(media and media[1])
local stamp=os.date('%Y%m%d_%H%M%S');local prefix='REA_ALPHA_RAMP_'..stamp..'_'
local codecs={}
for _,label in pairs(project:GetRenderCodecs('mov')) do
 if type(label)=='string' then
  if label:find('4444') and not label:find('XQ') then codecs.rgba=label end
  if label:lower():find('prores') and label:lower():find('hq') and not label:find('4444') then codecs.rgb=label end
 end
end
assert(codecs.rgb and codecs.rgba);assert(project:SetCurrentRenderMode(1))
local cases={
 {name='plain_a0',alpha=0},{name='plain_a025',alpha=.25},{name='plain_a05',alpha=.5},{name='plain_a1',alpha=1},
 {name='black_a05',alpha=.5,lower='black'},{name='green_a05',alpha=.5,lower='green'},
 {name='gen_a1_b025',alpha=1,blend=.25,back='generator'},{name='gen_a1_b05',alpha=1,blend=.5,back='generator'},{name='gen_a1_b075',alpha=1,blend=.75,back='generator'},
 {name='gen_a05_b025',alpha=.5,blend=.25,back='generator'},{name='gen_a05_b05',alpha=.5,blend=.5,back='generator'},{name='gen_a05_b1',alpha=.5,blend=1,back='generator'},
 {name='media_a05_b05',alpha=.5,blend=.5,back='media'}
}
local ids={};REA_ALPHA_RAMP_REPORT={prefix=prefix,ids=ids,rows={}}
for _,case in ipairs(cases) do
 local timeline=pool:CreateEmptyTimeline(prefix..case.name);assert(timeline and project:SetCurrentTimeline(timeline))
 local row={after={fusion_alpha_ramp=true,attempt=2,stamp=stamp,source=source,case=case,version=resolve:GetVersionString(),jobs={},nodes={},color={}},timeline=timeline:GetName(),completed=false}
 local a=row.after
 local ok,reason=pcall(function()
  assert(timeline:SetSetting('useCustomSettings','1'));assert(timeline:SetSetting('timelineResolutionWidth','640'));assert(timeline:SetSetting('timelineResolutionHeight','360'))
  a.timeline_settings={width=timeline:GetSetting('timelineResolutionWidth'),height=timeline:GetSetting('timelineResolutionHeight'),fps=timeline:GetSetting('timelineFrameRate')}
  for _,key in ipairs({'colorScienceMode','colorSpaceInput','colorSpaceTimeline','colorSpaceOutput','isAutoColorManage'}) do a.color[key]=project:GetSetting(key) end
  if case.lower then assert(timeline:AddTrack('video')) end
  local origin=timeline:GetStartFrame()
  local function append(track)
   local returned=pool:AppendToTimeline({{mediaPoolItem=media[1],startFrame=0,endFrame=12,recordFrame=origin,trackIndex=track,mediaType=1}})
   assert(returned and returned[1],'Video-only append returned no item')
   local c=timeline:GetItemListInTrack('video',track)[1];assert(c,'Requested video track empty: '..track);return c
  end
  local top=append(case.lower and 2 or 1);a.duration=top:GetDuration(true)
  local function set(n,key,value)
   assert(n:SetInput(key,value)~=false);local read=n:GetInput(key)
   if type(value)=='number' then assert(type(read)=='number' and math.abs(read-value)<1e-5,key..' readback differs') end
  end
  local function bg(comp,r,g,b,alpha)
   local n=comp:AddTool('Background');assert(n)
   set(n,'UseFrameFormatSettings',0);set(n,'Width',640);set(n,'Height',360)
   set(n,'TopLeftRed',r);set(n,'TopLeftGreen',g);set(n,'TopLeftBlue',b);set(n,'TopLeftAlpha',alpha);return n
  end
  local function find(comp,kind) for _,n in pairs(comp:GetToolList(false,kind)) do return n end end
  if case.lower then
   local c=append(1);local comp=c:AddFusionComp();assert(comp)
   assert(find(comp,'MediaOut'):ConnectInput('Input',bg(comp,0,case.lower=='green' and 1 or 0,0,1)))
  end
  local comp=top:AddFusionComp();assert(comp)
  local target=bg(comp,0,0,1,case.alpha)
  if case.blend then
   local back=case.back=='media' and find(comp,'MediaIn') or bg(comp,1,0,0,1)
   local merge=comp:AddTool('Merge');assert(merge);set(merge,'Blend',case.blend)
   assert(merge:ConnectInput('Background',back));assert(merge:ConnectInput('Foreground',target));target=merge
  end
  assert(find(comp,'MediaOut'):ConnectInput('Input',target))
  a.frame_format=comp:GetPrefs('Comp.FrameFormat')
  for _,n in pairs(comp:GetToolList(false)) do
   local attrs=n:GetAttrs();local entry={name=attrs.TOOLS_Name,class=attrs.TOOLS_RegID,inputs={}}
   for _,key in ipairs({'TopLeftRed','TopLeftGreen','TopLeftBlue','TopLeftAlpha','Blend','ApplyMode','Operator','Gain','ProcessAlpha','BurnIn','AlphaGain','Linear','PreMultiply','MultiplyByMask'}) do
    local good,value=pcall(function()return n:GetInput(key)end);if good and value~=nil then entry.inputs[key]=value end
   end
   a.nodes[#a.nodes+1]=entry
  end
  for _,kind in ipairs({'rgb','rgba'}) do
   assert(project:SetCurrentRenderFormatAndCodec('mov',codecs[kind]))
   local settings={SelectAllFrames=true,TargetDir=output,CustomName=timeline:GetName()..'_'..kind,ExportVideo=true,ExportAudio=false,FormatWidth=640,FormatHeight=360,FrameRate=24,ExportSubtitle=false}
   if kind=='rgba' then settings.ExportAlpha=true;settings.AlphaMode=1 end
   a.render_attempt={kind=kind,settings=settings}
   assert(project:SetRenderSettings(settings),'Render settings rejected: '..kind);local id=project:AddRenderJob();assert(id and id~='','Render job rejected: '..kind)
   a.jobs[#a.jobs+1]={id=id,kind=kind,codec=codecs[kind],settings=settings};ids[#ids+1]=id
  end
  row.completed=true
 end)
 if not ok then a.error=tostring(reason) end
 assert(timeline:AddMarker(0,ok and 'Green' or 'Red','REA_ALPHA_RAMP_EVIDENCE',json(row),1,json(row)));manager:SaveProject()
 REA_ALPHA_RAMP_REPORT.rows[#REA_ALPHA_RAMP_REPORT.rows+1]=row;print('REA_ALPHA_RAMP_EVIDENCE='..json(row))
end
if #ids>0 then
 local started=project:StartRendering(ids,false)
 local t=project:GetCurrentTimeline();local row={after={fusion_alpha_ramp_launch=true,prefix=prefix,ids=ids,started=started},timeline=t:GetName(),completed=true}
 assert(t:AddMarker(1,'Blue','REA_ALPHA_RAMP_LAUNCH',json(row),1,json(row)));manager:SaveProject()
end
resolve:OpenPage('edit')
