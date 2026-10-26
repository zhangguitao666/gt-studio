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
local ids={"6a5245fd-3977-4c51-bd36-0686b5ac2e88", "3870611e-c01e-4d42-9d0a-986017f3fcb0", "8ee28c9d-7332-4b0d-b8d6-aeb7338d3b79", "c2173347-dbe4-427b-9404-34d97500b816", "d95e1930-c866-4b3f-97ad-988ec3d88ffa", "08a9a612-3870-48c1-abc9-8376462aea37", "d0b6bb95-2035-4d4d-89bf-ac7a56bf2881", "c4d57546-eff8-468c-927f-47b21105b633"}
local row={after={audio_gain_status=true,jobs={},job_info={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
local t=p:GetCurrentTimeline();assert(t:GetName():find('REA_AUDIO_GAIN_',1,true)==1)
assert(t:AddMarker(2,'Green','REA_AUDIO_GAIN_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_AUDIO_GAIN_STATUS='..json(row))
