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
local ids={"4131fbe7-69b5-444b-8a14-0915d687cfd5", "75549c8a-2453-4f0a-83c6-d3da134ed715", "617cbba8-f6cb-45c0-be85-8a30202a0ece", "2573d272-2bbc-44c1-9ed6-44e2244d34b5", "ec93180b-dd37-408b-9d22-93eaf5dceb27", "0a1ce9d9-30d8-4e3b-adde-e0189615e7e4", "9e69db32-c08a-44bb-bbde-0c3d3f307621", "320da6d1-18b4-4667-af26-58e1434f1102", "a125cf74-cf03-4330-85a5-d62098c4ec12", "e9ea1eda-cfc3-4b57-bcd9-c04c3597fa17", "5dcf1c29-b2b0-49db-9681-d9dfa3ee0340", "1a73b283-7a04-497b-8efb-c84a84027559", "c6a02db8-4be1-4e14-9856-8f980fab6a8b", "71e64432-b87a-4ed9-bba3-c3bee8f32df0", "6f47e2e2-2181-4e2b-9142-941005d5aa11", "f6425beb-17cc-4f8f-80f3-ec4be308cd7c"}
local row={after={fusion_output_pair_status=true,jobs={},job_info={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
local t=p:GetCurrentTimeline();assert(t:GetName():find('REA_FUSION_20261022_164830_',1,true)==1)
assert(t:AddMarker(46,'Green','REA_FUSION_OUTPUT_PAIR_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_FUSION_OUTPUT_PAIR_STATUS='..json(row))
