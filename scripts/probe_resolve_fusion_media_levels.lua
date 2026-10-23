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
local pool=project:GetMediaPool();local root='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-level-native'
local prefix='REA_FUSION_LEVEL_'..os.date('%Y%m%d_%H%M%S')..'_';local ids={}
local codec
for _,label in pairs(project:GetRenderCodecs('mov')) do
 if type(label)=='string' and label:lower():find('prores') and label:lower():find('hq') and not label:find('4444') then codec=label end
end
assert(codec);assert(project:SetCurrentRenderMode(1));assert(project:SetCurrentRenderFormatAndCodec('mov',codec))
REA_FUSION_LEVEL_REPORT={prefix=prefix,ids=ids,rows={}}
for _,level in ipairs({'Auto','Full','Video'}) do
 local source=root..'/source_'..level:lower()..'.mov';local media=pool:ImportMedia({source});assert(media and media[1])
 local item=media[1];local before=item:GetClipProperty();local set_ok=item:SetClipProperty('Data Level',level)
 local after=item:GetClipProperty();local read=after['Data Level']
 -- These are new, owned source copies; never alter older reference pool items.
 for _,blend in ipairs({0,.25,.5,.75,1}) do
  local t=pool:CreateEmptyTimeline(prefix..level:lower()..'_b'..tostring(blend):gsub('%.','p'));assert(t and project:SetCurrentTimeline(t))
  local row={after={fusion_media_levels=true,prefix=prefix,source=source,level=level,blend=blend,alpha=.5,property_set_ok=set_ok,property_before=before,property_after=after,jobs={},nodes={},color={},version=resolve:GetVersionString()},timeline=t:GetName(),completed=false}
  local a=row.after
  local ok,reason=pcall(function()
   assert(set_ok~=false and read==level,'Data Level set/readback failed: '..tostring(read))
   assert(t:SetSetting('useCustomSettings','1'));assert(t:SetSetting('timelineResolutionWidth','640'));assert(t:SetSetting('timelineResolutionHeight','360'))
   for _,key in ipairs({'colorScienceMode','colorSpaceInput','colorSpaceTimeline','colorSpaceOutput','isAutoColorManage'}) do a.color[key]=project:GetSetting(key) end
   local clips=pool:AppendToTimeline({{mediaPoolItem=item,startFrame=0,endFrame=12,recordFrame=t:GetStartFrame(),trackIndex=1,mediaType=1}});assert(clips and clips[1])
   local clip=t:GetItemListInTrack('video',1)[1];assert(clip);local comp=clip:AddFusionComp();assert(comp)
   local function find(kind)for _,n in pairs(comp:GetToolList(false,kind)) do return n end end
   local function set(n,key,v)assert(n:SetInput(key,v)~=false);assert(math.abs(n:GetInput(key)-v)<1e-5,key..' readback')end
   local blue=comp:AddTool('Background');assert(blue)
   set(blue,'UseFrameFormatSettings',0);set(blue,'Width',640);set(blue,'Height',360);set(blue,'TopLeftRed',0);set(blue,'TopLeftGreen',0);set(blue,'TopLeftBlue',1);set(blue,'TopLeftAlpha',.5)
   local merge=comp:AddTool('Merge');assert(merge);set(merge,'Blend',blend)
   assert(merge:ConnectInput('Background',find('MediaIn')));assert(merge:ConnectInput('Foreground',blue));assert(find('MediaOut'):ConnectInput('Input',merge))
   for _,n in pairs(comp:GetToolList(false)) do
    local attrs=n:GetAttrs();local node={name=attrs.TOOLS_Name,class=attrs.TOOLS_RegID,inputs={}}
    for _,input in pairs(n:GetInputList() or {}) do
     local attrs=input:GetAttrs();local key=attrs.INPS_ID
     if key then local good,v=pcall(function()return n:GetInput(key)end);if good and (type(v)=='number' or type(v)=='string' or type(v)=='boolean') then node.inputs[key]=v end end
    end
    a.nodes[#a.nodes+1]=node
   end
   local settings={SelectAllFrames=true,TargetDir=root,CustomName=t:GetName(),ExportVideo=true,ExportAudio=false,FormatWidth=640,FormatHeight=360,FrameRate=24,ExportSubtitle=false}
   assert(project:SetRenderSettings(settings));local id=project:AddRenderJob();assert(id and id~='');a.jobs[#a.jobs+1]={id=id,codec=codec,settings=settings};ids[#ids+1]=id;row.completed=true
  end)
  if not ok then a.error=tostring(reason) end
  assert(t:AddMarker(0,ok and 'Green' or 'Red','REA_FUSION_LEVEL_EVIDENCE',json(row),1,json(row)));manager:SaveProject();REA_FUSION_LEVEL_REPORT.rows[#REA_FUSION_LEVEL_REPORT.rows+1]=row;print('REA_FUSION_LEVEL_EVIDENCE='..json(row))
 end
end
if #ids>0 then
 local started=project:StartRendering(ids,false);local t=project:GetCurrentTimeline();local row={after={fusion_media_levels_launch=true,prefix=prefix,ids=ids,started=started},timeline=t:GetName(),completed=true};assert(t:AddMarker(1,'Blue','REA_FUSION_LEVEL_LAUNCH',json(row),1,json(row)));manager:SaveProject()
end
resolve:OpenPage('edit')
