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
local ids={"81b8d294-7e2f-45d9-acfd-cc7dd791f9fd", "415fbe12-21ae-4e18-acb7-09472d59cda6", "f9e3c92c-4f29-41f8-860e-25b144a4e173", "6e9f0a1f-1ecf-40ea-9763-3dbea01fb671", "58d2cc84-5aca-484b-be71-2e5ed05965a5", "71150f12-e0c9-4030-bf94-92e3413dbb0f", "58464bc7-4ae8-4453-81ff-515b27d9a5b7", "358533ce-fbda-47af-a664-0e832bb9e127", "721ea5ec-2afb-4aca-987b-0a04b83fc462"}
local row={after={audio_boundary_status=true,jobs={},job_info={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
local t=p:GetCurrentTimeline();assert(t:GetName():find('REA_AUDIO_BOUNDARY_',1,true)==1)
assert(t:AddMarker(2,'Green','REA_AUDIO_BOUNDARY_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_AUDIO_BOUNDARY_STATUS='..json(row))
