-- Query exact captured job handles.
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
assert(p and p:GetName()=='REA Reference · 2026-10-21','Wrong reference project')
local ids={"c748b072-cf04-4334-80a2-d173b4168f30", "9dc1e977-1ae5-496f-852b-9e3113eabf83", "e2bd4465-7f50-457c-a905-e1fa6b4556b4", "f38aac91-9a62-4adc-9d77-705fbd4fd3ff", "7a8eeede-e471-4006-84a0-0bd8c433b979", "0ada2b53-2065-4830-98c3-376873b9ee7b", "b9800789-6bd7-45d4-b44b-a9cf7e43a095", "65b07af4-59c3-4609-97e2-ee951bb10f3b", "b6bcb277-d68d-4547-9aec-84c5e5a97cd8", "aaf42f0c-10f1-4d5a-9fb7-81dd8ce543c9", "be440d82-30ab-47af-9be1-924cdc29f010", "0f984741-683a-4b94-8edb-1ca596667029", "e3d6da6f-c547-4581-a3d7-8519e3d8e5c6", "24aa2a6a-6da8-40ff-8a90-022ef706c318"}
local row={after={audio_pan_status=true,jobs={},job_info={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
local t=p:GetCurrentTimeline();assert(t:GetName():find('REA_AUDIO_PAN_',1,true)==1)
assert(t:AddMarker(2,'Green','REA_AUDIO_PAN_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_AUDIO_PAN_STATUS='..json(row))
