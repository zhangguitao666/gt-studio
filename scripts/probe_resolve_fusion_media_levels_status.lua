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
local ids={"b758fb70-8b1c-415d-a8fa-a1bb5aa5e22d", "bdc150f5-6d7e-4829-ab2b-9cbc6d832e24", "05ce1aa0-69bf-4e08-b3e9-1945d1038eea", "0064d5a2-ba57-485c-b913-25b03664834f", "07a66cc6-f460-4361-855b-cee3a760b91c", "c4d779ac-cfb3-4827-a9f8-ea624fcad817", "91086e7d-ffe0-4931-bb7d-1746cc6e06d3", "18db5cfb-52c0-48c9-982f-6f76baf8b89c", "a83cc598-3a25-4f46-9d69-cbd627fab314", "e5c1bf11-dc46-4ffb-b203-94385b11be76", "d5128215-1462-4a0e-bcde-2ccf7f4cc8b9", "f7e816ac-ffd7-4124-85b0-d849eb373a97", "8bc958f2-b6c5-4a6a-930c-75bbd13e7278", "af6d4aa0-9a46-454a-a3cd-b07a63422778", "5d8be373-4429-40ce-992b-5c5439d756d2"}
local row={after={fusion_media_levels_status=true,jobs={},job_info={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
local t=p:GetCurrentTimeline();assert(t:GetName():sub(1,17)=='REA_FUSION_LEVEL_')
assert(t:AddMarker(2,'Green','REA_FUSION_LEVEL_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_FUSION_LEVEL_STATUS='..json(row))
