-- Historical second attempt: ProRes422 rejects ExportAlpha=false here.
-- Kept to reproduce the recorded rejection; the main paired probe omits
-- both alpha fields for ProRes422 and is the corrected request.
-- Re-export existing controlled comps without editing their nodes.
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

local m=resolve:GetProjectManager();local p=m:GetCurrentProject()
assert(p and p:GetName()=='REA Reference · 2026-10-21','Wrong reference project');assert(not p:IsRenderingInProgress(),'Reference render active')
local root='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-output-pairs'
local prefix='REA_FUSION_20261022_164830_';local stamp=os.date('%Y%m%d_%H%M%S');local ids={};local available=p:GetRenderCodecs('mov') or {};local codecs={}
for _,v in pairs(available) do codecs[v]=true end
local profiles={{name='prores422',codec='ProRes422HQ',alpha=false},{name='ffv1_rgb',codec='FFV1IntraRGBA_16',alpha=false}}
local wanted={background_half=true,transform_upper_right=true,rotation_90=true,merge_half=true};local timelines={}
for i=1,p:GetTimelineCount() do local t=p:GetTimelineByIndex(i);local name=t:GetName();if name:sub(1,#prefix)==prefix and wanted[name:sub(#prefix+1)] then timelines[#timelines+1]=t end end
assert(#timelines==4,'Expected four original controlled timelines')
for _,t in ipairs(timelines) do
 assert(p:SetCurrentTimeline(t));local mode=t:GetName():sub(#prefix+1);local clip=t:GetItemListInTrack('video',1)[1];assert(clip);local comp=clip:GetFusionCompByIndex(1);assert(comp)
 local nodes={}
 for _,n in pairs(comp:GetToolList(false)) do
  local attrs=n:GetAttrs();local item={name=attrs.TOOLS_Name,class=attrs.TOOLS_RegID,inputs={}}
  for _,key in ipairs({'Width','Height','UseFrameFormatSettings','TopLeftRed','TopLeftGreen','TopLeftBlue','TopLeftAlpha','Center','Pivot','Size','Angle','Blend','FilterMethod','FlattenTransform','InvertTransform','Edges','CorrectEdges','ClippingMode'}) do
   local value=n:GetInput(key);if value~=nil then item.inputs[key]=value end
  end
  nodes[#nodes+1]=item
 end
 for i,profile in ipairs(profiles) do
  local frame=36+i;assert(not (t:GetMarkers() or {})[frame],'Evidence marker slot occupied')
  local row={after={fusion_output_pair=true,stamp=stamp,mode=mode,profile=profile,nodes=nodes,version=resolve:GetVersionString(),timeline_settings={width=t:GetSetting('timelineResolutionWidth'),height=t:GetSetting('timelineResolutionHeight'),fps=t:GetSetting('timelineFrameRate')},clip_properties=clip:GetProperty(),project_color={}},timeline=t:GetName(),completed=false};local a=row.after
  local ok,err=pcall(function()
   for _,key in ipairs({'colorScienceMode','timelineColorSpace','timelineGamma','outputColorSpace','outputGamma','colorManagementPreset','isAutoColorManage','timelineSampleRate'}) do a.project_color[key]=p:GetSetting(key) end
   assert(codecs[profile.codec],'Codec not enumerated');assert(p:SetCurrentRenderFormatAndCodec('mov',profile.codec));assert(p:SetCurrentRenderMode(1))
   local settings={SelectAllFrames=true,TargetDir=root,CustomName=t:GetName()..'_'..stamp..'_'..profile.name,ExportVideo=true,ExportAudio=false,FormatWidth=640,FormatHeight=360,FrameRate=24,ExportAlpha=profile.alpha,ExportSubtitle=false}
   if profile.alpha then settings.AlphaMode=1 end
   assert(p:SetRenderSettings(settings),'Paired export settings rejected');local id=p:AddRenderJob();assert(id and id~='');a.settings=settings;a.job_id=id;ids[#ids+1]=id;row.completed=true
  end)
  if not ok then a.error=tostring(err) end
  -- Dedicated new markers only; keep previous probes intact.
  assert(t:AddMarker(frame,ok and 'Green' or 'Red','REA_FUSION_OUTPUT_PAIR_RGB_RETRY',json(row),1,json(row)));m:SaveProject()
 end
end
if #ids>0 then local started=p:StartRendering(ids,false);local t=p:GetCurrentTimeline();local row={after={fusion_output_pair_launch=true,stamp=stamp,ids=ids,started=started},timeline=t:GetName(),completed=true};assert(t:AddMarker(39,'Blue','REA_FUSION_OUTPUT_PAIR_RGB_RETRY_LAUNCH',json(row),1,json(row)));m:SaveProject() end
resolve:OpenPage('edit')
