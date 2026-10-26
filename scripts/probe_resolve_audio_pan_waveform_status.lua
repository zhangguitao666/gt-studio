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
local ids={"5da22e1e-20a1-4484-8b6d-8d246b546f2b", "3d69f51c-6d5e-426e-9fbf-f108d222ea3d", "f9a18858-f238-4935-bd60-9e3937015b38", "b1ad33b0-ebbc-4c99-8556-39d5aeca2559", "9ccd5946-e330-41c2-a5d3-3c423b0b471d", "8daced72-f532-48f7-b42d-26ec3275f9ba", "95ba45eb-18bd-43e3-a5c4-12fb4d7bde0d"}
local row={after={audio_pan_waveform_status=true,jobs={},job_info={},rendering=p:IsRenderingInProgress()},timeline=p:GetCurrentTimeline():GetName(),completed=true}
local wanted={};for _,id in ipairs(ids) do wanted[id]=true;row.after.jobs[#row.after.jobs+1]={id=id,status=p:GetRenderJobStatus(id)} end
for _,job in ipairs(p:GetRenderJobList()) do if wanted[job.JobId] then row.after.job_info[#row.after.job_info+1]=job end end
local t=p:GetCurrentTimeline();assert(t:GetName():find('REA_AUDIO_PAN_WAVEFORM_',1,true)==1)
assert(t:AddMarker(2,'Green','REA_AUDIO_PAN_WAVEFORM_STATUS',json(row),1,json(row)));m:SaveProject();print('REA_AUDIO_PAN_WAVEFORM_STATUS='..json(row))
