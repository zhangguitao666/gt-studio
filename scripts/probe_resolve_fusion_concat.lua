-- Owned synthetic concatenation versus explicit-flatten controls.
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

local manager=resolve:GetProjectManager();local p=manager:GetCurrentProject()
assert(p and p:GetName()=='REA Reference · 2026-10-21','Wrong reference project')
assert(not p:IsRenderingInProgress(),'Reference render active')
local root='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-concat-native-v2'
local pool=p:GetMediaPool();local imported=pool:ImportMedia({root..'/source320.mov'});assert(imported and imported[1])
local prefix='REA_FUSION_CONCAT_V2_'..os.date('%Y%m%d_%H%M%S')..'_';local ids={};local codec
for _,v in pairs(p:GetRenderCodecs('mov') or {}) do if type(v)=='string' and v:find('4444') and not v:find('XQ') then codec=v end end
assert(codec and p:SetCurrentRenderFormatAndCodec('mov',codec));assert(p:SetCurrentRenderMode(1))
local cases={'identity','translate_return','translate_return_flattened','shrink_restore','shrink_restore_flattened','shrink_rotate_restore'}
for _,name in ipairs(cases) do
 local t=pool:CreateEmptyTimeline(prefix..name);assert(t and p:SetCurrentTimeline(t))
 local row={after={fusion_concat=true,name=name,version=resolve:GetVersionString(),source=root..'/source320.mov',nodes={}},timeline=t:GetName(),completed=false};local a=row.after
 local ok,err=pcall(function()
  assert(t:SetSetting('useCustomSettings','1'));assert(t:SetSetting('timelineResolutionWidth','320'));assert(t:SetSetting('timelineResolutionHeight','320'))
  local clips=pool:AppendToTimeline({{mediaPoolItem=imported[1],startFrame=0,endFrame=12,recordFrame=t:GetStartFrame(),trackIndex=1}});assert(clips and clips[1]);local clip=clips[1]
  a.clip={duration=clip:GetDuration(true),properties=clip:GetProperty()};local comp=clip:AddFusionComp();assert(comp)
  local media_in,media_out
  for _,n in pairs(comp:GetToolList(false)) do local cls=n:GetAttrs().TOOLS_RegID;if cls=='MediaIn' then media_in=n elseif cls=='MediaOut' then media_out=n end end
  assert(media_in and media_out);local target=media_in
  if name=='identity' then
   local identity=comp:AddTool('Transform');assert(identity and identity:ConnectInput('Input',media_in)~=false);target=identity
  else
   local first=comp:AddTool('Transform');local second=comp:AddTool('Transform');assert(first and second)
   local function set(n,key,value)
    assert(n:SetInput(key,value)~=false);local v=n:GetInput(key)
    if type(value)=='number' then assert(math.abs(v-value)<1e-6) end
   end
   if name:find('translate') then set(first,'Center',{1.5,.5});set(second,'Center',{-.5,.5})
   else set(first,'Size',.25);set(second,'Size',4) end
   if name=='shrink_rotate_restore' then set(first,'Angle',17);set(second,'Angle',-17) end
   if name:find('flattened') then set(first,'FlattenTransform',1) end
   assert(first:ConnectInput('Input',media_in)~=false);assert(second:ConnectInput('Input',first)~=false);target=second
  end
  assert(media_out:ConnectInput('Input',target)~=false)
  for _,n in pairs(comp:GetToolList(false)) do
   local attrs=n:GetAttrs();local item={name=attrs.TOOLS_Name,class=attrs.TOOLS_RegID,inputs={}}
   for _,key in ipairs({'Center','Size','Angle','FilterMethod','FlattenTransform','InvertTransform'}) do local value=n:GetInput(key);if value~=nil then item.inputs[key]=value end end
   a.nodes[#a.nodes+1]=item
  end
  a.timeline_settings={width=t:GetSetting('timelineResolutionWidth'),height=t:GetSetting('timelineResolutionHeight'),fps=t:GetSetting('timelineFrameRate')}
  local settings={SelectAllFrames=true,TargetDir=root,CustomName=t:GetName(),ExportVideo=true,ExportAudio=false,FormatWidth=320,FormatHeight=320,FrameRate=24,ExportAlpha=true,AlphaMode=1,ExportSubtitle=false}
  assert(p:SetRenderSettings(settings));local id=p:AddRenderJob();assert(id and id~='');a.job_id=id;a.settings=settings;ids[#ids+1]=id;row.completed=true
 end)
 if not ok then a.error=tostring(err) end
 assert(t:AddMarker(0,ok and 'Green' or 'Red','REA_FUSION_CONCAT_EVIDENCE',json(row),1,json(row)));manager:SaveProject()
end
if #ids>0 then local started=p:StartRendering(ids,false);local t=p:GetCurrentTimeline();local row={after={fusion_concat_launch=true,ids=ids,started=started},timeline=t:GetName(),completed=true};assert(t:AddMarker(1,'Blue','REA_FUSION_CONCAT_LAUNCH',json(row),1,json(row)));manager:SaveProject() end
resolve:OpenPage('edit')
