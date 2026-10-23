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
local ids={"7e964346-d1fa-492f-989a-c88f2cfa1a7e","8343abf7-244c-4bd6-86ce-58980695ef9d","3fa399ea-8da1-40d6-b804-4c560a500259","d5387932-7bcd-4661-9f73-bb2963fd22bf","cf965f5a-a2e8-4013-8df9-c06165e2f70e","c9248c38-6a8e-4d1f-a7fb-11ab745ae3c5","3f6a1cd0-cdf8-47e2-b4c1-c77b8d201f96","f673b6eb-6b19-4a44-9eaa-0876d310c301","d2bc0937-2439-4efe-ae96-6813befefd14","11bea383-f336-407c-a9ce-6f7159ba3aff","d17dccd9-b4ad-4ebc-881f-d8f7fa4e6095","ef6dfe04-b80b-401a-ad22-d8a455544997","45244f41-7757-42a5-8ec5-be53856b3fa0","6a300397-17b1-45cc-8f94-ac5a06b71a38","de0f37a3-56dd-41d0-9d1a-7d08e045228d","af6aff03-debf-4e2b-a558-2a3bdd2b95d4","ebd0275b-b6a3-4cf0-9018-6f500ab1adb8","fdc8549c-812d-4150-89ea-0aa0368d6bbb","a2a3854f-78ce-4604-a53f-08c5208684ec","a7f078ea-7672-4ece-b031-3f8b616e8b37","df575895-bd3d-4645-aeab-d66911423cf5","a3894fc4-6bf4-4576-add8-0392de7c36df","0b8d5bc0-5321-4488-897d-52edb3b91afd","9ce1b73a-cdb0-4a1b-bb34-73db2cda514a","efdcd9a1-9e98-4922-b485-93b5e2e68bf6","340684e4-05c0-4516-9fe3-2dac1ef38973"}
local row={after={fusion_alpha_ramp_status=true,jobs={},job_info={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
local t=p:GetCurrentTimeline();assert(t:GetName():sub(1,15)=='REA_ALPHA_RAMP_')
assert(t:AddMarker(2,'Green','REA_ALPHA_RAMP_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_ALPHA_RAMP_STATUS='..json(row))
