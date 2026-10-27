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
assert(p and p:GetName()=='REA Reference · 2026-10-21');assert(not p:IsRenderingInProgress())
local prefix='REA_FUSION_LEVEL_20261023_101653_'
local wanted={auto_b1=true,video_b1=true,full_b0p75=true,full_b0p5=true}
local selected={}
for i=1,p:GetTimelineCount() do local t=p:GetTimelineByIndex(i);local name=t:GetName();if name:sub(1,#prefix)==prefix and wanted[name:sub(#prefix+1)] then selected[#selected+1]=t end end
assert(#selected==4)
local codec='FFV1IntraRGBA_16';local available=false;for _,v in pairs(p:GetRenderCodecs('mov')) do if v==codec then available=true end end;assert(available)
assert(p:SetCurrentRenderFormatAndCodec('mov',codec));assert(p:SetCurrentRenderMode(1))
local root='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-level-rgba';local stamp=os.date('%Y%m%d_%H%M%S');local ids={}
for _,t in ipairs(selected) do
 assert(p:SetCurrentTimeline(t));assert(not (t:GetMarkers() or {})[10]);assert(not (t:GetMarkers() or {})[11])
 local clip=t:GetItemListInTrack('video',1)[1];assert(clip and clip:GetDuration(true)==12);local comp=clip:GetFusionCompByIndex(1);assert(comp)
 local row={after={fusion_level_rgba=true,stamp=stamp,version=resolve:GetVersionString(),data_level=clip:GetMediaPoolItem():GetClipProperty()['Data Level'],nodes={}},timeline=t:GetName(),completed=false};local a=row.after
 local ok,err=pcall(function()
  for _,n in pairs(comp:GetToolList(false)) do
   local at=n:GetAttrs();local item={name=at.TOOLS_Name,class=at.TOOLS_RegID,inputs={}}
   for _,key in ipairs({'Depth','Width','Height','UseFrameFormatSettings','TopLeftRed','TopLeftGreen','TopLeftBlue','TopLeftAlpha','Center','Blend'}) do local v=n:GetInput(key);if v~=nil then item.inputs[key]=v end end
   a.nodes[#a.nodes+1]=item
  end
  local settings={SelectAllFrames=true,TargetDir=root,CustomName=t:GetName()..'_rgba_'..stamp,ExportVideo=true,ExportAudio=false,FormatWidth=640,FormatHeight=360,FrameRate=24,ExportAlpha=true,AlphaMode=1,ExportSubtitle=false}
  assert(p:SetRenderSettings(settings));local id=p:AddRenderJob();assert(id and id~='');a.job_id=id;a.settings=settings;ids[#ids+1]=id;row.completed=true
 end)
 if not ok then a.error=tostring(err) end
 assert(t:AddMarker(10,ok and 'Green' or 'Red','REA_FUSION_LEVEL_RGBA',json(row),1,json(row)));m:SaveProject()
end
if #ids>0 then local started=p:StartRendering(ids,false);local t=p:GetCurrentTimeline();local row={after={fusion_level_rgba_launch=true,stamp=stamp,ids=ids,started=started},timeline=t:GetName(),completed=true};assert(t:AddMarker(11,'Blue','REA_FUSION_LEVEL_RGBA_LAUNCH',json(row),1,json(row)));m:SaveProject() end
resolve:OpenPage('edit')
