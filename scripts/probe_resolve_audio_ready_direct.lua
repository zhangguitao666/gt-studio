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
local m=resolve:GetProjectManager();local p=m:GetCurrentProject();assert(p and p:GetName()=='REA Reference · 2026-10-21');assert(not p:IsRenderingInProgress())
local id='6e9f0a1f-1ecf-40ea-9763-3dbea01fb671';local row={after={audio_ready_direct=true,id=id,before=p:GetRenderJobStatus(id)},completed=true}
local target
for i=1,p:GetTimelineCount() do local t=p:GetTimelineByIndex(i);if t:GetName()=='REA_AUDIO_BOUNDARY_20261023_161607_dc_single' then target=t end end
assert(target and p:SetCurrentTimeline(target));row.timeline=target:GetName()
if row.after.before.JobStatus=='Ready' then local ok,value=pcall(function()return p:StartRendering(id)end);row.after.call_ok=ok;row.after.value=value end
row.after.after=p:GetRenderJobStatus(id);row.after.io_type=type(io)
assert(target:AddMarker(7,'Blue','REA_AUDIO_READY_DIRECT',json(row),1,json(row)));m:SaveProject()
if type(io)=='table' and type(io.open)=='function' then local f=io.open('/Users/zgt/agent/resolve-reconstruction/workspace/audio-boundary-native/ready-direct.json','w');if f then f:write(json(row));f:close() end end
