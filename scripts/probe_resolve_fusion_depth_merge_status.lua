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
local ids={"89b0da6c-e4d7-476e-a258-793a550e6d6f", "da788d8f-cb48-4613-96df-379af8fb954e", "c7a05663-9a69-4875-a176-47ed2557919e", "c44cf0d6-bbdd-45f7-bff2-f9788570642b", "3b637e34-059b-40df-a05d-09022b4606ca", "7f1b86bc-10f9-4984-be31-1a69d1d1b941", "e6b1a1c5-bf7d-4583-a65c-08f542a8ce7b"}
local row={after={fusion_depth_merge_status=true,jobs={},job_info={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
local t=p:GetCurrentTimeline();assert(t:GetName():find('REA_FUSION_DEPTH_MERGE_',1,true)==1)
assert(t:AddMarker(2,'Green','REA_FUSION_DEPTH_MERGE_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_FUSION_DEPTH_MERGE_STATUS='..json(row))
