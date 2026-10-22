-- Existing dedicated synthetic timelines only; new alpha exports.
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
local prefix='REA_FUSION_20261022_164830_'
local codec=nil;for _,label in pairs(project:GetRenderCodecs('mov')) do if type(label)=='string' and label:find('4444') and not label:find('XQ') then codec=label end end
assert(codec,'No ProRes4444 codec');assert(project:SetCurrentRenderFormatAndCodec('mov',codec));assert(project:SetCurrentRenderMode(1))
local ids={}
for i=1,project:GetTimelineCount() do
 local t=project:GetTimelineByIndex(i)
 if t:GetName():sub(1,#prefix)==prefix then
  assert(project:SetCurrentTimeline(t))
  for _,alpha_mode in ipairs({0,1}) do
   local settings={SelectAllFrames=true,TargetDir='/Users/zgt/agent/resolve-reconstruction/workspace/fusion-native-alpha',CustomName=t:GetName()..'_alpha'..alpha_mode,ExportVideo=true,ExportAudio=false,FormatWidth=640,FormatHeight=360,FrameRate=24,ExportAlpha=true,AlphaMode=alpha_mode,ExportSubtitle=false}
   local row={after={alpha_export=true,mode=alpha_mode,codec=codec,settings=settings},timeline=t:GetName(),completed=false}
   local ok,err=pcall(function()
    assert(project:SetRenderSettings(settings),'Alpha settings rejected');row.after.readback=project:GetRenderSettings()
    local id=project:AddRenderJob();assert(id and id~='','No alpha job');row.after.job_id=id;ids[#ids+1]=id;row.completed=true
   end)
   if not ok then row.after.error=tostring(err) end
   t:AddMarker(3+alpha_mode,'Purple','REA_FUSION_ALPHA_EVIDENCE',json(row),1,json(row));manager:SaveProject();print('REA_FUSION_ALPHA_EVIDENCE='..json(row))
  end
 end
end
if #ids>0 then
 local started=project:StartRendering(ids,false)
 local t=project:GetCurrentTimeline();local row={after={alpha_launch=true,ids=ids,started=started},timeline=t:GetName(),completed=true}
 t:AddMarker(5,'Blue','REA_FUSION_ALPHA_LAUNCH',json(row),1,json(row));manager:SaveProject()
end
