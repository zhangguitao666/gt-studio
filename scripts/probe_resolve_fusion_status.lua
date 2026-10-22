-- Read selected reference job handles and retain a dedicated timeline marker.
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
local ids={"3b56e2ed-8cae-424d-8b6a-b6e4b541fcab","ca23dadb-ccaf-4b33-badd-a1ab33b33048","25db0df8-10a5-433e-9d1a-fa93d620ddda","bce4109d-fc4d-4a5f-90d8-0e7cbba08c95","a6a7f45f-8ca1-44bc-9328-2d1d06cb73da","3ebf891d-ea5b-44f5-b1f2-36a6c8b84ce0","0c77ccbf-4a8b-4b54-94ba-b226ba72c0fa","1256223b-106c-4252-a371-361d2de35b7c","d8adabb5-5b09-497e-a7b0-85b33e6f24da","55b2ed64-d3b8-4dda-b62c-986c8f38f97c","82adaa68-4241-4231-888a-179ebd41bcbe","04f8c94d-3871-4247-8126-e138897fcfdc","31faed28-0f91-4f0a-a54d-43290593cd26","4b3e4b88-55e4-4856-a483-95635a672998","07611650-3748-47a0-9d33-e1a9990fd801","1178b7cc-868b-4437-92df-0f2ffc8f2749","49c8de74-bac9-45b0-9aed-1461c552a938","be2f6186-42a3-451d-ad0e-e7a71ebdd739","402bb8a2-4da4-4f62-8c77-633948c8b7c7","5dd4815d-63ac-4bac-9e0d-2342f5242f46","a5dbf6d7-48fe-4f9c-8d29-98fdeceb78e3","c1381be6-66ea-4325-ae5d-0cde1050fded","c69a47f3-790b-4067-a4a3-0d0f8208a857","2adec4b9-cb6a-48e1-a7b0-c66eb174f1c5"}
local row={after={fusion_final_status=true,jobs={},job_info={},project_color={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
for key,value in pairs(p:GetSetting()) do if key:lower():find('color') or key:lower():find('gamma') then row.after.project_color[key]=value end end
local t=p:GetCurrentTimeline();assert(t:GetName():sub(1,11)=='REA_FUSION_')
assert(t:AddMarker(9,'Green','REA_FUSION_FINAL_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_FUSION_FINAL_STATUS='..json(row))
